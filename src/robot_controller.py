import asyncio

from src.dev_connection.interface import WSClientInterface
from src.dev_connection.udp_frame_sender import UdpFrameSender
from src.hardware.gpio.gpio_controller import GPIOController
from src.hardware.gpio.encoder_controller import EncoderController
from src.hardware.i2c.interface import I2CPWMInterface
from src.hardware.oak_d.interface import CameraInterface
from src.hardware.respeaker.interface import MicArrayInterface
from src.hardware.sd_card.interface import SdCardInterface
from src.hardware.ads1115.interface import ADS1115Interface
from src.hardware.lidar.interface import LidarInterface

from .robot_state import RobotState
from .services.command_processor import CommandProcessor
from .services.camera_streamer import CameraStreamer
from .services.audio_streamer import AudioStreamer
from .logic.robot_logic import RobotLogic
from .workers.camera_worker import CameraWorker
from .workers.mic_worker import MicWorker
from .ai.voice import Voice
from .workers.ads1115_worker import ADS1115Worker
from .workers.lidar_worker import LidarWorker
from .workers.slam_worker import SlamWorker
from .workers.encoder_worker import EncoderWorker


class RobotController:
    def __init__(self, config: dict, command_queue: asyncio.Queue, gpio: GPIOController, encoder: EncoderController, i2c_pwm: I2CPWMInterface, camera: CameraInterface, mic_array: MicArrayInterface, sd_card: SdCardInterface, ads1115: ADS1115Interface, lidar: LidarInterface, ws: WSClientInterface):
        self.config: dict = config
        self.state: RobotState = RobotState()
        self.sd_card: SdCardInterface = sd_card

        camera_stream_config = config.get("camera_stream", {})

        self.udp_frame_sender = UdpFrameSender(
            host=camera_stream_config.get("udp_host", "192.168.1.162"),
            port=camera_stream_config.get("udp_port", 8766),
            chunk_size=camera_stream_config.get("chunk_size", 1400),
        )

        self.command_processor = CommandProcessor(
            command_queue=command_queue,
            gpio=gpio,
            encoder=encoder,
            i2c_pwm=i2c_pwm,
            state=self.state,
            ws=ws,
            udp_frame_sender=self.udp_frame_sender,
        )

        self.camera_worker = CameraWorker(
            state=self.state,
            camera=camera
        )

        self.mic_worker = MicWorker(
            state=self.state,
            mic_array=mic_array
        )

        self.ads1115_worker = ADS1115Worker(
            state=self.state,
            ads1115=ads1115
        )

        self.lidar_worker = LidarWorker(
            state=self.state,
            lidar=lidar,
            config=config,
        )

        self.slam_worker = SlamWorker(
            state=self.state,
            config=config,
        )

        self.encoder_worker = EncoderWorker(
            state=self.state,
            encoder=encoder,
        )

        voice_control_config = config.get("voice", {})

        self.voice = Voice(
            state=self.state,
            model_path=voice_control_config.get("model_path", "/home/gremlin/gremlin/model"),
            logs=voice_control_config.get("dev_logs", False)
        )

        fps = config.get("oak_d", {}).get("fps") or 15

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
        self.voice.start()
        self.ads1115_worker.start()
        self.lidar_worker.start()
        self.slam_worker.start()
        self.encoder_worker.start()

        tasks = [
            asyncio.create_task(self.command_processor.run()),
            asyncio.create_task(self.command_processor.run_wheel_state_writer()),
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
            await self.ads1115_worker.stop()
            await self.lidar_worker.stop()
            await self.slam_worker.stop()
            await self.encoder_worker.stop()
            self.voice.stop()
            self.udp_frame_sender.close()
            self.sd_card.stop()