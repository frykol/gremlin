import asyncio

from src.dev_connection.interface import WSClientInterface
from src.hardware.gpio.gpio_controller import GPIOController
from src.hardware.i2c.i2c_pwm import i2cPWM
from src.hardware.oak_d.interface import CameraInterface

from .robot_state import RobotState
from .services.command_processor import CommandProcessor
from .services.camera_streamer import CameraStreamer
from .logic.robot_logic import RobotLogic
from .workers.camera_worker import CameraWorker


class RobotController:
    def __init__(self, config: dict, command_queue: asyncio.Queue, gpio: GPIOController, i2c_pwm: i2cPWM, camera: CameraInterface, ws: WSClientInterface):
        self.config: dict = config
        self.state: RobotState = RobotState()

        self.command_processor = CommandProcessor(
            command_queue=command_queue,
            gpio=gpio,
            i2c_pwm=i2c_pwm,
            state=self.state
        )

        self.camera_worker = CameraWorker(
            state=self.state,
            camera=camera
        )

        fps = config.get("fps") or 15

        self.camera_streamer = CameraStreamer(
            #camera=camera,
            ws=ws,
            state=self.state,
            fps=fps
        )

        self.logic = RobotLogic(
            gpio=gpio,
            i2c_pwm=i2c_pwm
        )

        self.i2c_pwm = i2c_pwm

    async def run(self):
        self.camera_worker.start()

        tasks = [
            asyncio.create_task(self.command_processor.run()),
            asyncio.create_task(self.camera_streamer.run()),
            asyncio.create_task(self.logic.run()),
        ]

        try:
            await asyncio.gather(*tasks)

        finally:
            for task in tasks:
                task.cancel()

            for i in range(4):
                self.i2c_pwm.set_pwm(i, 0, 0)

            await self.camera_worker.stop()