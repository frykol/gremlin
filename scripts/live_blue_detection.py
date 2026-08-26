"""
Test wykrywania niebieskiego koloru na zywo z kamery (webcam laptopa/PC,
nie wymaga sprzetu robota) - uzywa tego samego progu HSV co produkcyjny
color_detector.py, wiec to co widac tutaj = to co widzialby band_detection
na robocie.

Uzycie:
    python scripts/live_blue_detection.py
    python scripts/live_blue_detection.py --camera 1
    python scripts/live_blue_detection.py --config config.json

Sterowanie w oknie:
    q / ESC - wyjscie
    s       - zapisz biezaca klatke (oryginal + maska + nalozenie) do pliku
"""

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.hardware.color_detection.color_detector import BLUE_HSV_LOWER, BLUE_HSV_UPPER, DEFAULT_BLUE_RATIO_THRESHOLD

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"
SNAPSHOT_DIR = Path(__file__).resolve().parent / "live_blue_detection_snapshots"


def load_hsv_bounds(config_path: Path):
    if not config_path.exists():
        return BLUE_HSV_LOWER, BLUE_HSV_UPPER, DEFAULT_BLUE_RATIO_THRESHOLD

    config = json.loads(config_path.read_text())
    band_config = config.get("band_detection", {})

    hsv_lower = np.array(band_config.get("hsv_lower", BLUE_HSV_LOWER.tolist()))
    hsv_upper = np.array(band_config.get("hsv_upper", BLUE_HSV_UPPER.tolist()))
    blue_ratio_threshold = band_config.get("blue_ratio_threshold", DEFAULT_BLUE_RATIO_THRESHOLD)

    return hsv_lower, hsv_upper, blue_ratio_threshold


def build_frame(image: np.ndarray, hsv_lower: np.ndarray, hsv_upper: np.ndarray, blue_ratio_threshold: float):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, hsv_lower, hsv_upper)
    ratio = float(np.count_nonzero(mask)) / float(mask.size)
    detected = ratio >= blue_ratio_threshold

    overlay = image.copy()
    overlay[mask > 0] = (0, 255, 0)
    overlay = cv2.addWeighted(image, 0.4, overlay, 0.6, 0)

    label = "WYKRYTO NIEBIESKI" if detected else "brak"
    color = (0, 255, 0) if detected else (0, 0, 255)
    cv2.putText(overlay, f"ratio={ratio:.3f}  prog={blue_ratio_threshold:.3f}  {label}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

    mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    combined = np.hstack([image, mask_bgr, overlay])

    return combined, ratio, detected


def main():
    parser = argparse.ArgumentParser(description="Live test wykrywania niebieskiego koloru z kamery.")
    parser.add_argument("--camera", type=int, default=0, help="Indeks kamery (domyslnie 0)")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="Sciezka do config.json")
    args = parser.parse_args()

    hsv_lower, hsv_upper, blue_ratio_threshold = load_hsv_bounds(Path(args.config))
    print(f"hsv_lower={hsv_lower.tolist()} hsv_upper={hsv_upper.tolist()} blue_ratio_threshold={blue_ratio_threshold}")

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f"Nie mozna otworzyc kamery o indeksie {args.camera}")
        sys.exit(1)

    print("q/ESC - wyjscie, s - zapisz klatke")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("Nie udalo sie odczytac klatki z kamery.")
                break

            combined, ratio, detected = build_frame(frame, hsv_lower, hsv_upper, blue_ratio_threshold)
            cv2.imshow("live blue detection (oryginal | maska | nalozenie)", combined)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            elif key == ord("s"):
                SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
                out_path = SNAPSHOT_DIR / f"snapshot_{int(time.time())}.jpg"
                cv2.imwrite(str(out_path), combined)
                print(f"zapisano: {out_path}")
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
