"""
Samodzielne narzedzie do szybkiego sprawdzania wykrywania niebieskiego koloru
(bez calego pipeline'u pozy/nog) - uzywa tego samego progu HSV co
band_detection, zeby wynik byl 1:1 z tym, co robi produkcyjny kod.

Uzycie:
    python scripts/test_blue_detection.py sciezka/do/zdjecia.jpg
    python scripts/test_blue_detection.py sciezka/do/folderu/
    python scripts/test_blue_detection.py sciezka/do/zdjecia.jpg --save out/

Bez --save otwiera okno z podgladem (oryginal | maska | nalozenie),
ESC/dowolny klawisz przechodzi do kolejnego zdjecia.
Z --save zapisuje wizualizacje do plikow zamiast otwierac okno (dziala
tez bez GUI/na headless).
"""

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.hardware.color_detection.color_detector import BLUE_HSV_LOWER, BLUE_HSV_UPPER, DEFAULT_BLUE_RATIO_THRESHOLD

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


def load_hsv_bounds(config_path: Path):
    if not config_path.exists():
        return BLUE_HSV_LOWER, BLUE_HSV_UPPER, DEFAULT_BLUE_RATIO_THRESHOLD

    config = json.loads(config_path.read_text())
    band_config = config.get("band_detection", {})

    hsv_lower = np.array(band_config.get("hsv_lower", BLUE_HSV_LOWER.tolist()))
    hsv_upper = np.array(band_config.get("hsv_upper", BLUE_HSV_UPPER.tolist()))
    blue_ratio_threshold = band_config.get("blue_ratio_threshold", DEFAULT_BLUE_RATIO_THRESHOLD)

    return hsv_lower, hsv_upper, blue_ratio_threshold


def analyze_image(image: np.ndarray, hsv_lower: np.ndarray, hsv_upper: np.ndarray):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, hsv_lower, hsv_upper)
    ratio = float(np.count_nonzero(mask)) / float(mask.size)

    mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)

    overlay = image.copy()
    overlay[mask > 0] = (0, 255, 0)
    overlay = cv2.addWeighted(image, 0.4, overlay, 0.6, 0)

    return mask, mask_bgr, overlay, ratio


def build_side_by_side(image, mask_bgr, overlay):
    height = image.shape[0]

    def resize_to_height(img):
        h, w = img.shape[:2]
        scale = height / h
        return cv2.resize(img, (int(w * scale), height))

    return np.hstack([image, resize_to_height(mask_bgr), resize_to_height(overlay)])


def process_image(path: Path, hsv_lower, hsv_upper, blue_ratio_threshold, save_dir: Path | None):
    image = cv2.imread(str(path))
    if image is None:
        print(f"pominieto (nie mozna wczytac): {path}")
        return

    mask, mask_bgr, overlay, ratio = analyze_image(image, hsv_lower, hsv_upper)
    detected = ratio >= blue_ratio_threshold

    label = "WYKRYTO" if detected else "brak"
    print(f"{path.name}: niebieski_ratio={ratio:.3f} prog={blue_ratio_threshold:.3f} -> {label}")

    combined = build_side_by_side(image, mask_bgr, overlay)
    cv2.putText(
        combined,
        f"ratio={ratio:.3f} ({label})",
        (10, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (0, 255, 0) if detected else (0, 0, 255),
        2,
    )

    if save_dir is not None:
        save_dir.mkdir(parents=True, exist_ok=True)
        out_path = save_dir / f"{path.stem}_blue_detection.jpg"
        cv2.imwrite(str(out_path), combined)
        print(f"  zapisano: {out_path}")
    else:
        cv2.imshow(f"oryginal | maska | nalozenie - {path.name}", combined)
        cv2.waitKey(0)
        cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description="Test wykrywania niebieskiego koloru (HSV) na zdjeciach.")
    parser.add_argument("path", help="Plik ze zdjeciem albo folder ze zdjeciami")
    parser.add_argument("--save", help="Folder na zapisane wizualizacje (zamiast okna podgladu)")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="Sciezka do config.json")
    args = parser.parse_args()

    hsv_lower, hsv_upper, blue_ratio_threshold = load_hsv_bounds(Path(args.config))
    print(f"hsv_lower={hsv_lower.tolist()} hsv_upper={hsv_upper.tolist()} blue_ratio_threshold={blue_ratio_threshold}")

    target = Path(args.path)
    save_dir = Path(args.save) if args.save else None

    if target.is_dir():
        image_paths = sorted(
            p for p in target.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp")
        )
        if not image_paths:
            print(f"Brak zdjec w {target}")
            sys.exit(1)
    else:
        image_paths = [target]

    for path in image_paths:
        process_image(path, hsv_lower, hsv_upper, blue_ratio_threshold, save_dir)


if __name__ == "__main__":
    main()
