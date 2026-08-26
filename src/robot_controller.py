import asyncio
import time

import numpy as np

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
from .workers.band_detection_worker import BandDetectionWorker
from .hardware.band_detection.detector import BandDetector
from .hardware.band_detection.mediapipe_pose_estimator import MediaPipePoseEstimator
from .workers.color_detection_worker import ColorDetectionWorker


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

        band_detection_config = config.get("band_detection", {})

        pose_estimator_kwargs = {}
        if band_detection_config.get("model_path"):
            pose_estimator_kwargs["model_path"] = band_detection_config["model_path"]

        band_detector_kwargs = {}
        if band_detection_config.get("hsv_lower"):
            band_detector_kwargs["hsv_lower"] = np.array(band_detection_config["hsv_lower"])
        if band_detection_config.get("hsv_upper"):
            band_detector_kwargs["hsv_upper"] = np.array(band_detection_config["hsv_upper"])

        self.band_detection_worker = BandDetectionWorker(
            detector=BandDetector(
                pose_estimator=MediaPipePoseEstimator(**pose_estimator_kwargs),
                roi_half_size=band_detection_config.get("roi_half_size", 15),
                blue_ratio_threshold=band_detection_config.get("blue_ratio_threshold", 0.15),
                **band_detector_kwargs,
            ),
            state=self.state,
            poll_interval=band_detection_config.get("poll_interval", 0.2),
            debounce_count=band_detection_config.get("debounce_count", 5),
        )

        color_detection_config = config.get("color_detection", {})

        color_detector_kwargs = {}
        if color_detection_config.get("hsv_lower"):
            color_detector_kwargs["hsv_lower"] = np.array(color_detection_config["hsv_lower"])
        if color_detection_config.get("hsv_upper"):
            color_detector_kwargs["hsv_upper"] = np.array(color_detection_config["hsv_upper"])

        self.color_detection_worker = ColorDetectionWorker(
            state=self.state,
            poll_interval=color_detection_config.get("poll_interval", 0.2),
            blue_ratio_threshold=color_detection_config.get("blue_ratio_threshold", 0.15),
            **color_detector_kwargs,
        )

        self.logic = RobotLogic(
            gpio=gpio,
            i2c_pwm=i2c_pwm,
            state=self.state,
        )

        self.i2c_pwm = i2c_pwm
        self.status_log_interval = config.get("status_log_interval", 10)

    async def status_logger(self):
        while True:
            await asyncio.sleep(self.status_log_interval)

            ads1115 = self.state.last_ads1115_state
            band = self.state.band_detection_state
            lidar_points = len(self.state.lidar_point_buffer) if self.state.lidar_point_buffer else 0

            print(
                f"[status] t={time.strftime('%H:%M:%S')} ads1115={ads1115} "
                f"band_detection(both={band.both_detected if band else None}, "
                f"left={band.left if band else None}, right={band.right if band else None}) "
                f"lidar_points={lidar_points}"
            )

    async def run(self):
        self.sd_card.start()
        self.camera_worker.start()
        self.mic_worker.start()
        self.ads1115_worker.start()
        self.lidar_worker.start()
        self.slam_worker.start()
        self.encoder_worker.start()
        self.band_detection_worker.start()
        self.color_detection_worker.start()

        tasks = [
            asyncio.create_task(self.command_processor.run()),
            asyncio.create_task(self.command_processor.run_wheel_state_writer()),
            asyncio.create_task(self.camera_streamer.run()),
            asyncio.create_task(self.audio_streamer.run()),
            asyncio.create_task(self.logic.run()),
            asyncio.create_task(self.voice.run()),
            asyncio.create_task(self.status_logger()),
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
            await self.band_detection_worker.stop()
            await self.color_detection_worker.stop()
            self.udp_frame_sender.close()
            self.sd_card.stop()