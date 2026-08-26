import asyncio
import base64
import time

import cv2

from src.hardware.band_detection.detector import BandDetector, BandDetectionResult
from src.robot_state import BandDetectionState, RobotState


class BandDetectionWorker:
    def __init__(
        self,
        detector: BandDetector,
        state: RobotState,
        poll_interval: float = 0.2,
        debounce_count: int = 5,
        debug_frame_max_width: int = 480,
        debug_frame_jpeg_quality: int = 60,
    ):
        self.detector: BandDetector = detector
        self.state: RobotState = state
        self.poll_interval: float = poll_interval
        self.debounce_count: int = debounce_count
        self.debug_frame_max_width: int = debug_frame_max_width
        self.debug_frame_jpeg_quality: int = debug_frame_jpeg_quality

        self._consecutive_failures: int = 0

        self.running: bool = False
        self.task: asyncio.Task | None = None

    def _build_debug_frame(self, image, result: BandDetectionResult) -> str:
        debug_image = image.copy()
        roi_half_size = self.detector.roi_half_size

        for ankle, detected in ((result.left_ankle, result.left), (result.right_ankle, result.right)):
            if ankle is None:
                continue

            x, y = ankle
            color = (0, 200, 0) if detected else (0, 0, 220)

            cv2.rectangle(
                debug_image,
                (x - roi_half_size, y - roi_half_size),
                (x + roi_half_size, y + roi_half_size),
                color,
                2,
            )
            cv2.circle(debug_image, (x, y), 3, color, -1)

        height, width = debug_image.shape[:2]
        if width > self.debug_frame_max_width:
            scale = self.debug_frame_max_width / width
            debug_image = cv2.resize(debug_image, (int(width * scale), int(height * scale)))

        ok, buffer = cv2.imencode(
            ".jpg",
            debug_image,
            [cv2.IMWRITE_JPEG_QUALITY, self.debug_frame_jpeg_quality],
        )

        if not ok:
            return ""

        return base64.b64encode(buffer.tobytes()).decode("ascii")

    def process_frame(self, image) -> None:
        try:
            result = self.detector.detect(image)
        except Exception as exc:
            print(f"Band detection error: {exc}")
            return

        if self.state.band_detection_state is None:
            self.state.band_detection_state = BandDetectionState()

        band_state = self.state.band_detection_state

        if result.both:
            self._consecutive_failures = 0
            band_state.both_detected = True
        else:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.debounce_count:
                band_state.both_detected = False

        band_state.left = result.left
        band_state.right = result.right
        band_state.last_update = time.time()

        try:
            band_state.debug_frame = self._build_debug_frame(image, result)
        except Exception as exc:
            print(f"Band detection debug frame error: {exc}")

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
