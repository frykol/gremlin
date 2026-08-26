from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from src.hardware.color_detection.color_detector import (
    BLUE_HSV_LOWER,
    BLUE_HSV_UPPER,
    DEFAULT_BLUE_RATIO_THRESHOLD,
    is_band_present,
)
from .interface import PoseEstimatorInterface


@dataclass(eq=True)
class BandDetectionResult:
    left: bool
    right: bool
    both: bool
    left_ankle: Optional[Tuple[int, int]] = None
    right_ankle: Optional[Tuple[int, int]] = None


class BandDetector:
    def __init__(
        self,
        pose_estimator: PoseEstimatorInterface,
        roi_half_size: int = 15,
        blue_ratio_threshold: float = DEFAULT_BLUE_RATIO_THRESHOLD,
        hsv_lower: np.ndarray = BLUE_HSV_LOWER,
        hsv_upper: np.ndarray = BLUE_HSV_UPPER,
    ):
        self.pose_estimator = pose_estimator
        self.roi_half_size = roi_half_size
        self.blue_ratio_threshold = blue_ratio_threshold
        self.hsv_lower = hsv_lower
        self.hsv_upper = hsv_upper

    def detect(self, image: np.ndarray) -> BandDetectionResult:
        ankles = self.pose_estimator.get_ankle_positions(image)

        left = is_band_present(image, ankles.left, self.roi_half_size, self.blue_ratio_threshold, self.hsv_lower, self.hsv_upper)
        right = is_band_present(image, ankles.right, self.roi_half_size, self.blue_ratio_threshold, self.hsv_lower, self.hsv_upper)

        return BandDetectionResult(
            left=left,
            right=right,
            both=left and right,
            left_ankle=ankles.left,
            right_ankle=ankles.right,
        )
