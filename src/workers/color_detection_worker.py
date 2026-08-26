import asyncio
import base64
import time

import cv2
import numpy as np

from src.hardware.color_detection.color_detector import BLUE_HSV_LOWER, BLUE_HSV_UPPER, DEFAULT_BLUE_RATIO_THRESHOLD, blue_mask
from src.robot_state import ColorDetectionState, RobotState


class ColorDetectionWorker:
    def __init__(
        self,
        state: RobotState,
        poll_interval: float = 0.2,
        blue_ratio_threshold: float = DEFAULT_BLUE_RATIO_THRESHOLD,
        hsv_lower: np.ndarray = BLUE_HSV_LOWER,
        hsv_upper: np.ndarray = BLUE_HSV_UPPER,
        debug_frame_max_width: int = 480,
        debug_frame_jpeg_quality: int = 60,
    ):
        self.state: RobotState = state
        self.poll_interval: float = poll_interval
        self.blue_ratio_threshold: float = blue_ratio_threshold
        self.hsv_lower: np.ndarray = hsv_lower
        self.hsv_upper: np.ndarray = hsv_upper
        self.debug_frame_max_width: int = debug_frame_max_width
        self.debug_frame_jpeg_quality: int = debug_frame_jpeg_quality

        self.running: bool = False
        self.task: asyncio.Task | None = None

    def _build_debug_frame(self, image: np.ndarray, mask: np.ndarray) -> str:
        overlay = image.copy()
        overlay[mask > 0] = (0, 255, 0)
        overlay = cv2.addWeighted(image, 0.4, overlay, 0.6, 0)

        height, width = overlay.shape[:2]
        if width > self.debug_frame_max_width:
            scale = self.debug_frame_max_width / width
            overlay = cv2.resize(overlay, (int(width * scale), int(height * scale)))

        ok, buffer = cv2.imencode(
            ".jpg",
            overlay,
            [cv2.IMWRITE_JPEG_QUALITY, self.debug_frame_jpeg_quality],
        )

        if not ok:
            return ""

        return base64.b64encode(buffer.tobytes()).decode("ascii")

    def process_frame(self, image: np.ndarray) -> None:
        try:
            mask = blue_mask(image, self.hsv_lower, self.hsv_upper)
            ratio = float(np.count_nonzero(mask)) / float(mask.size)
        except Exception as exc:
            print(f"Color detection error: {exc}")
            return

        if self.state.color_detection_state is None:
            self.state.color_detection_state = ColorDetectionState()

        color_state = self.state.color_detection_state
        color_state.detected = ratio >= self.blue_ratio_threshold
        color_state.blue_ratio = ratio
        color_state.last_update = time.time()

        try:
            color_state.debug_frame = self._build_debug_frame(image, mask)
        except Exception as exc:
            print(f"Color detection debug frame error: {exc}")

    async def run(self):
        while self.running:
            frame = self.state.last_frame

            if frame is not None:
                self.process_frame(frame.image)

            await asyncio.sleep(self.poll_interval)

    def start(self):
        if self.running:
            return

        self.running = True
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        self.running = False

        if self.task is not None:
            await self.task
