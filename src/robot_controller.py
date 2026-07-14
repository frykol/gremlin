import asyncio

from src.dev_connection.interface import WSClientInterface
from src.dev_connection.udp_frame_sender import UdpFrameSender
from src.hardware.gpio.gpio_controller import GPIOController
from src.hardware.i2c.i2c_pwm import i2cPWM
from src.hardware.oak_d.interface import CameraInterface
from src.hardware.respeaker.factory import create_mic_array
from src.hardware.respeaker.interface import MicArrayInterface
from src.hardware.sd_card.interface import SdCardInterface

from .robot_state import RobotState
from .services.command_processor import CommandProcessor
from .services.camera_streamer import CameraStreamer
from .services.audio_streamer import AudioStreamer
from .logic.robot_logic import RobotLogic
from .workers.camera_worker import CameraWorker
from .workers.mic_worker import MicWorker
from .workers.voice_worker import VoiceWorker


class RobotController:
    def __init__(self, config: dict, command_queue: asyncio.Queue, gpio: GPIOController, i2c_pwm: i2cPWM, camera: CameraInterface, mic_array: MicArrayInterface, sd_card: SdCardInterface, ws: WSClientInterface):
        self.config: dict = config
        self.state: RobotState = RobotState()
        self.sd_card: SdCardInterface = sd_card

        self.command_processor = CommandProcessor(
            command_queue=command_queue,
            gpio=gpio,
            i2c_pwm=i2c_pwm,
            state=self.state,
            ws=ws
        )

        self.camera_worker = CameraWorker(
            state=self.state,
            camera=camera
        )

        self.mic_worker = MicWorker(
            state=self.state,
            mic_array=mic_array
        )

        voice_config = config.get("voice", {})

        self.voice_worker = VoiceWorker(
            mic_array=create_mic_array(config),
            model_path=voice_config.get("model_path", "/robot/model"),
        )

        fps = config.get("oak_d", {}).get("fps") or 15

        camera_stream_config = config.get("camera_stream", {})

        self.udp_frame_sender = UdpFrameSender(
            host=camera_stream_config.get("udp_host", "192.168.1.162"),
            port=camera_stream_config.get("udp_port", 8766),
            chunk_size=camera_stream_config.get("chunk_size", 1400),
        )

        self.camera_streamer = CameraStreamer(
            udp_sender=self.udp_frame_sender,
            state=self.state,
            fps=fps
        )

        respeaker_config = config.get("respeaker", {})
        audio_channel = respeaker_config.get("stream_channel", 0)

        self.audio_streamer = AudioStreamer(
            ws=ws,
            state=self.state,
            channel=audio_channel,
        )

        self.logic = RobotLogic(
            gpio=gpio,
            i2c_pwm=i2c_pwm
        )

        self.i2c_pwm = i2c_pwm

    async def run(self):
        self.sd_card.start()
        self.camera_worker.start()
        self.mic_worker.start()
        self.voice_worker.start()

        tasks = [
            asyncio.create_task(self.command_processor.run()),
            asyncio.create_task(self.camera_streamer.run()),
            asyncio.create_task(self.audio_streamer.run()),
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
            await self.mic_worker.stop()
            await self.voice_worker.stop()
            self.udp_frame_sender.close()
            self.sd_card.stop()