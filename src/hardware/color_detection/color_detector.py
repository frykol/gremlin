from typing import Optional, Tuple

import cv2
import numpy as np

# Zakres niebieskiego w HSV (OpenCV: H 0-179, S/V 0-255) dobrany pod
# nasycone, jednolite niebieskie opaski (nie pod odcienie jeansu/skory).
BLUE_HSV_LOWER = np.array([90, 80, 40])
BLUE_HSV_UPPER = np.array([130, 255, 255])

DEFAULT_BLUE_RATIO_THRESHOLD = 0.15


def _clip_roi(image: np.ndarray, center: Tuple[int, int], roi_half_size: int):
    height, width = image.shape[:2]
    cx, cy = center

    x0 = max(0, cx - roi_half_size)
    y0 = max(0, cy - roi_half_size)
    x1 = min(width, cx + roi_half_size)
    y1 = min(height, cy + roi_half_size)

    if x1 <= x0 or y1 <= y0:
        return None

    return image[y0:y1, x0:x1]


def blue_pixel_ratio(
    image: np.ndarray,
    center: Optional[Tuple[int, int]],
    roi_half_size: int = 15,
    hsv_lower: np.ndarray = BLUE_HSV_LOWER,
    hsv_upper: np.ndarray = BLUE_HSV_UPPER,
) -> float:
    if center is None:
        return 0.0

    roi = _clip_roi(image, center, roi_half_size)
    if roi is None or roi.size == 0:
        return 0.0

    hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv_roi, hsv_lower, hsv_upper)

    return float(np.count_nonzero(mask)) / float(mask.size)


def is_band_present(
    image: np.ndarray,
    center: Optional[Tuple[int, int]],
    roi_half_size: int = 15,
    blue_ratio_threshold: float = DEFAULT_BLUE_RATIO_THRESHOLD,
    hsv_lower: np.ndarray = BLUE_HSV_LOWER,
    hsv_upper: np.ndarray = BLUE_HSV_UPPER,
) -> bool:
    return blue_pixel_ratio(image, center, roi_half_size, hsv_lower, hsv_upper) >= blue_ratio_threshold


def blue_mask(
    image: np.ndarray,
    hsv_lower: np.ndarray = BLUE_HSV_LOWER,
    hsv_upper: np.ndarray = BLUE_HSV_UPPER,
) -> np.ndarray:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, hsv_lower, hsv_upper)


def frame_blue_ratio(
    image: np.ndarray,
    hsv_lower: np.ndarray = BLUE_HSV_LOWER,
    hsv_upper: np.ndarray = BLUE_HSV_UPPER,
) -> float:
    mask = blue_mask(image, hsv_lower, hsv_upper)
    return float(np.count_nonzero(mask)) / float(mask.size)
