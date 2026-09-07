from typing import List, Optional, Tuple

import cv2
import numpy as np

# Zakres niebieskiego w HSV (OpenCV: H 0-179, S/V 0-255) dobrany pod
# nasycone, jednolite niebieskie opaski (nie pod odcienie jeansu/skory).
# V (jasnosc) ma podniesiony dolny prog, zeby odrzucac ciemny granat/czern,
# ktore w niskim swietle wpadaja w ten sam zakres odcienia H co niebieski.
BLUE_HSV_LOWER = np.array([90, 80, 120])
BLUE_HSV_UPPER = np.array([130, 255, 255])

# Zakres zoltego w HSV - tlo/opaska pod ktorym musi lezec zielony marker,
# zeby uznac go za wiarygodne wykrycie (a nie przypadkowy zielony obiekt).
# Podniesiony dolny prog V, zeby lapac tylko jasny, wyrazisty zolty
# (odrzuca przygaszone/ciemne odcienie zbliajace sie do brazu/oliwki).
YELLOW_HSV_LOWER = np.array([20, 80, 140])
YELLOW_HSV_UPPER = np.array([35, 255, 255])

DEFAULT_BLUE_RATIO_THRESHOLD = 0.15
DEFAULT_MIN_BLOB_AREA_PX = 150

# x, y, width, height in pixel coordinates of the source frame
BoundingBox = Tuple[int, int, int, int]


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


def find_blue_bboxes(
    mask: np.ndarray,
    min_area_px: int = DEFAULT_MIN_BLOB_AREA_PX,
    require_horizontal: bool = True,
    min_aspect_ratio: Optional[float] = None,
    min_rectangularity: float = 0.0,
) -> List[BoundingBox]:
    """Zwraca bounding boxy oddzielnych skupisk niebieskiego na masce, posortowane
    od najwiekszego. Male skupiska (szum) ponizej min_area_px sa odrzucane.

    require_horizontal / min_aspect_ratio: skupisko musi miec stosunek
    szerokosc/wysokosc >= max(1.0 jesli require_horizontal, min_aspect_ratio)
    - odrzuca skupiska wyzsze niz szersze albo o zbyt kwadratowym ksztalcie
    (np. przypadkowe pionowe/kwadratowe obiekty; opaska jest pozioma).

    min_rectangularity: minimalny stosunek pola konturu do pola jego bbox-a
    (0-1) - odrzuca ksztalty, ktore nie wypelniaja prostokata (np. kola,
    nieregularne plamy), zeby przepuszczac tylko ksztalty zblizone do
    prostokata."""
    if min_aspect_ratio is not None:
        effective_min_ratio = max(1.0, min_aspect_ratio) if require_horizontal else min_aspect_ratio
    else:
        effective_min_ratio = 1.0 if require_horizontal else 0.0

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area_px:
            continue
        bbox = cv2.boundingRect(contour)
        _x, _y, w, h = bbox
        if h == 0 or w / h < effective_min_ratio:
            continue
        bbox_area = w * h
        if bbox_area > 0 and (area / bbox_area) < min_rectangularity:
            continue
        boxes.append((bbox, area))

    boxes.sort(key=lambda item: item[1], reverse=True)

    return [box for box, _ in boxes]


def bboxes_intersect(a: BoundingBox, b: BoundingBox) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b

    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def any_bbox_intersects(target: Optional[BoundingBox], candidates: List[BoundingBox]) -> bool:
    if target is None:
        return False

    return any(bboxes_intersect(target, candidate) for candidate in candidates)


def find_bbox_on_background(
    foreground_bboxes: List[BoundingBox],
    background_bboxes: List[BoundingBox],
) -> Optional[BoundingBox]:
    """Zwraca pierwszy (najwiekszy) bbox z foreground_bboxes, ktory nachodzi na
    jakikolwiek bbox z background_bboxes - np. zielony marker lezacy na zoltym
    tle. None jesli zaden nie pasuje."""
    for candidate in foreground_bboxes:
        if any(bboxes_intersect(candidate, background) for background in background_bboxes):
            return candidate

    return None
