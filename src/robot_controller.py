import asyncio
import os

from src.dev_connection.interface import WSClientInterface
from src.hardware.gpio.gpio_controller import GPIOController
from src.hardware.i2c.i2c_pwm import i2cPWM
from src.hardware.oak_d.interface import CameraInterface

from .robot_state import RobotState
from .services.command_processor import CommandProcessor
from .services.camera_streamer import CameraStreamer
from .services.camera_preview import CameraPreview
from .logic.robot_logic import RobotLogic
from .workers.camera_worker import CameraWorker
from .workers.gesture_worker import GestureWorker
from .services.hand_gestures import HandGestureDetector
from .services.gesture_executor import GestureExecutor


def _display_available() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


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
        stream_config = config.get("stream", {})

        self.camera_streamer = CameraStreamer(
            ws=ws,
            state=self.state,
            fps=fps,
            flip_vertical=stream_config.get("flip_vertical", False),
            overlay_gestures=stream_config.get("overlay_gestures", False),
        )

        self.logic = RobotLogic(
            gpio=gpio,
            i2c_pwm=i2c_pwm
        )

        gestures_config = config.get("gestures", {})
        self.preview_enabled = gestures_config.get("preview", False) and _display_available()

        self.camera_preview: CameraPreview | None = None
        if self.preview_enabled:
            preview_title = gestures_config.get(
                "window_title",
                "Niezawodne Sterowanie Robotem",
            )
            self.camera_preview = CameraPreview(
                state=self.state,
                window_name=preview_title,
            )
        self.i2c_pwm = i2c_pwm

        self.gestures_enabled = gestures_config.get("enabled", False)
        self.gesture_worker: GestureWorker | None = None
        stream_flip_vertical = stream_config.get("flip_vertical", False)
        if self.gestures_enabled:
            detector = HandGestureDetector(
                max_hands=gestures_config.get("max_hands", 2),
                min_detection_confidence=gestures_config.get("min_detection_confidence", 0.7),
                min_tracking_confidence=gestures_config.get("min_tracking_confidence", 0.5),
                mirrored=gestures_config.get("mirrored", False),
            )
            executor = GestureExecutor(
                execute_commands=gestures_config.get("execute_commands", False),
            )
            self.gesture_worker = GestureWorker(
                state=self.state,
                detector=detector,
                executor=executor,
                flip_vertical=stream_flip_vertical,
            )

    async def run(self):
        self.camera_worker.start()
        if self.gesture_worker is not None:
            self.gesture_worker.start()

        tasks = [
            asyncio.create_task(self.command_processor.run()),
            asyncio.create_task(self.camera_streamer.run()),
        ]

        if self.preview_enabled and self.camera_preview is not None:
            tasks.append(asyncio.create_task(self.camera_preview.run()))
        else:
            tasks.append(asyncio.create_task(self.logic.run()))

        try:
            if self.preview_enabled:
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
            else:
                await asyncio.gather(*tasks)

        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

            for i in range(4):
                self.i2c_pwm.set_pwm(i, 0, 0)

            if self.gesture_worker is not None:
                await self.gesture_worker.stop()

            await self.camera_worker.stop()