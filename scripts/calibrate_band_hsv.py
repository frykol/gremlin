"""
Kalibracja zakresu HSV pod konkretne (odblaskowe, niebieskie) opaski.

Dla kazdego zdjecia w folderze otwiera okno, w ktorym mysza zaznaczasz
prostokat obejmujacy opaske (ROI). Zbiera piksele HSV ze wszystkich
zaznaczonych regionow i wypisuje rekomendowany band_detection.hsv_lower /
hsv_upper do wklejenia w config.json.

Uzycie:
    python scripts/calibrate_band_hsv.py sciezka/do/folderu/ze/zdjeciami

Sterowanie w oknie selectROI:
    - zaznacz prostokat myszka, zatwierdz ENTER/SPACE
    - ESC albo puste zaznaczenie pomija zdjecie
"""

import sys
from pathlib import Path

import cv2
import numpy as np


def collect_hsv_samples(image_paths: list[Path]) -> np.ndarray:
    samples = []

    for path in image_paths:
        image = cv2.imread(str(path))
        if image is None:
            print(f"pominieto (nie mozna wczytac): {path}")
            continue

        display = image
        max_dim = 1000
        scale = 1.0
        h, w = image.shape[:2]
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            display = cv2.resize(image, (int(w * scale), int(h * scale)))

        window = f"zaznacz opaske: {path.name} (ENTER=zatwierdz, ESC=pomin)"
        x, y, rw, rh = cv2.selectROI(window, display, showCrosshair=True)
        cv2.destroyWindow(window)

        if rw == 0 or rh == 0:
            print(f"pominieto (brak zaznaczenia): {path}")
            continue

        x0, y0 = int(x / scale), int(y / scale)
        x1, y1 = int((x + rw) / scale), int((y + rh) / scale)
        roi = image[y0:y1, x0:x1]

        hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        samples.append(hsv_roi.reshape(-1, 3))
        print(f"zebrano {hsv_roi.shape[0] * hsv_roi.shape[1]} pikseli z {path.name}")

    if not samples:
        return np.empty((0, 3), dtype=np.uint8)

    return np.concatenate(samples, axis=0)


def recommend_range(samples: np.ndarray, low_pct: float = 2.0, high_pct: float = 98.0):
    if samples.size == 0:
        raise ValueError("Brak zebranych probek - nie mozna wyliczyc zakresu.")

    # Hue jest cykliczny (0-179 w OpenCV), ale dla niebieskiego (~90-130)
    # nie przechodzi przez 0, wiec zwykle percentyle wystarcza.
    lower = np.percentile(samples, low_pct, axis=0)
    upper = np.percentile(samples, high_pct, axis=0)

    # Odblaskowy material daje piksele o wysokim V i niskim S (prawie biale
    # rozbielenie) - obnizamy dolny prog S i podnosimy gorny prog V, zeby to
    # zlapac, ale nie schodzimy do zera, zeby nie lapac tla.
    s_low = max(0.0, lower[1] - 30)
    v_low = max(0.0, lower[2] - 20)

    hsv_lower = np.array([lower[0], s_low, v_low]).clip(0, 255).astype(int)
    hsv_upper = np.array([upper[0], 255, 255]).clip(0, 255).astype(int)
    hsv_lower[0] = max(0, hsv_lower[0])
    hsv_upper[0] = min(179, hsv_upper[0])

    return hsv_lower, hsv_upper


def main():
    if len(sys.argv) != 2:
        print(f"Uzycie: python {sys.argv[0]} sciezka/do/folderu/ze/zdjeciami")
        sys.exit(1)

    folder = Path(sys.argv[1])
    image_paths = sorted(
        p for p in folder.iterdir()
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp")
    )

    if not image_paths:
        print(f"Brak zdjec w {folder}")
        sys.exit(1)

    print(f"Znaleziono {len(image_paths)} zdjec.")
    samples = collect_hsv_samples(image_paths)

    hsv_lower, hsv_upper = recommend_range(samples)

    print()
    print("Rekomendowany zakres HSV (wklej do config.json -> band_detection):")
    print(f'  "hsv_lower": [{hsv_lower[0]}, {hsv_lower[1]}, {hsv_lower[2]}],')
    print(f'  "hsv_upper": [{hsv_upper[0]}, {hsv_upper[1]}, {hsv_upper[2]}]')
    print()
    print("Wskazowka: jesli w podgladzie /bands w apce widac za duzo falszywych")
    print("trafien - podnies blue_ratio_threshold; jesli za malo - obnizy go")
    print("lub rozszerz hsv_lower/hsv_upper.")


if __name__ == "__main__":
    main()
