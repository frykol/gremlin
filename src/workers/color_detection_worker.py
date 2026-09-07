import asyncio
import base64
import time

import cv2
import numpy as np

from src.hardware.color_detection.color_detector import (
    BLUE_HSV_LOWER,
    BLUE_HSV_UPPER,
    DEFAULT_BLUE_RATIO_THRESHOLD,
    DEFAULT_MIN_BLOB_AREA_PX,
    YELLOW_HSV_LOWER,
    YELLOW_HSV_UPPER,
    blue_mask,
    find_blue_bboxes,
    find_bbox_on_background,
)
from src.robot_state import ColorDetectionState, RobotState

TARGET_BBOX_COLOR_BGR = (0, 165, 255)
TARGET_BBOX_THICKNESS = 2
GREEN_BBOX_COLOR_BGR = (255, 255, 255)
YELLOW_BBOX_COLOR_BGR = (0, 255, 255)
BBOX_THICKNESS = 2


class ColorDetectionWorker:
    def __init__(
        self,
        state: RobotState,
        poll_interval: float = 0.2,
        blue_ratio_threshold: float = DEFAULT_BLUE_RATIO_THRESHOLD,
        hsv_lower: np.ndarray = BLUE_HSV_LOWER,
        hsv_upper: np.ndarray = BLUE_HSV_UPPER,
        yellow_hsv_lower: np.ndarray = YELLOW_HSV_LOWER,
        yellow_hsv_upper: np.ndarray = YELLOW_HSV_UPPER,
        debug_frame_max_width: int = 480,
        debug_frame_jpeg_quality: int = 60,
        min_blob_area_px: int = DEFAULT_MIN_BLOB_AREA_PX,
    ):
        self.state: RobotState = state
        self.poll_interval: float = poll_interval
        self.blue_ratio_threshold: float = blue_ratio_threshold
        self.hsv_lower: np.ndarray = hsv_lower
        self.hsv_upper: np.ndarray = hsv_upper
        self.yellow_hsv_lower: np.ndarray = yellow_hsv_lower
        self.yellow_hsv_upper: np.ndarray = yellow_hsv_upper
        self.debug_frame_max_width: int = debug_frame_max_width
        self.debug_frame_jpeg_quality: int = debug_frame_jpeg_quality
        self.min_blob_area_px: int = min_blob_area_px

        self.running: bool = False
        self.task: asyncio.Task | None = None

    def _build_debug_frame(
        self,
        image: np.ndarray,
        mask: np.ndarray,
        green_bboxes: list,
        yellow_bboxes: list,
        target_bbox: tuple | None,
    ) -> str:
        overlay = image.copy()
        overlay[mask > 0] = (0, 255, 0)
        overlay = cv2.addWeighted(image, 0.4, overlay, 0.6, 0)

        for x, y, w, h in yellow_bboxes:
            cv2.rectangle(overlay, (x, y), (x + w, y + h), YELLOW_BBOX_COLOR_BGR, BBOX_THICKNESS)

        for x, y, w, h in green_bboxes:
            cv2.rectangle(overlay, (x, y), (x + w, y + h), GREEN_BBOX_COLOR_BGR, BBOX_THICKNESS)

        if target_bbox is not None:
            x, y, w, h = target_bbox
            cv2.rectangle(overlay, (x, y), (x + w, y + h), TARGET_BBOX_COLOR_BGR, TARGET_BBOX_THICKNESS)

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
            green_bboxes = find_blue_bboxes(
                mask, self.min_blob_area_px, min_aspect_ratio=1.2, min_rectangularity=0.3
            )

            yellow_mask = blue_mask(image, self.yellow_hsv_lower, self.yellow_hsv_upper)
            yellow_bboxes = find_blue_bboxes(yellow_mask, self.min_blob_area_px, require_horizontal=False)
        except Exception as exc:
            print(f"Color detection error: {exc}")
            return

        target_bbox = find_bbox_on_background(green_bboxes, yellow_bboxes)

        if self.state.color_detection_state is None:
            self.state.color_detection_state = ColorDetectionState()

        color_state = self.state.color_detection_state
        color_state.detected = ratio >= self.blue_ratio_threshold
        color_state.blue_ratio = ratio
        color_state.last_update = time.time()
        color_state.blue_bboxes = green_bboxes
        color_state.yellow_bboxes = yellow_bboxes
        color_state.target_bbox = target_bbox
        color_state.green_on_yellow_detected = target_bbox is not None

        try:
            color_state.debug_frame = self._build_debug_frame(image, mask, green_bboxes, yellow_bboxes, target_bbox)
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
