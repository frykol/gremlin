import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import cv2
import numpy as np

from .onnx_hand.mp_handpose import MPHandPose
from .onnx_hand.mp_palmdet import MPPalmDet

PALM_MODEL_URL = (
    "https://huggingface.co/opencv/palm_detection_mediapipe/resolve/main/"
    "palm_detection_mediapipe_2023feb.onnx"
)
HANDPOSE_MODEL_URL = (
    "https://huggingface.co/opencv/handpose_estimation_mediapipe/resolve/main/"
    "handpose_estimation_mediapipe_2023feb.onnx"
)

MODELS_DIR = Path(__file__).resolve().parent / "onnx_hand" / "models"
PALM_MODEL_PATH = MODELS_DIR / "palm_detection_mediapipe_2023feb.onnx"
HANDPOSE_MODEL_PATH = MODELS_DIR / "handpose_estimation_mediapipe_2023feb.onnx"

FINGER_TIPS = [8, 12, 16, 20]
FINGER_BASES = [5, 9, 13, 17]

HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (0, 9), (9, 10), (10, 11), (11, 12),
    (0, 13), (13, 14), (14, 15), (15, 16),
    (0, 17), (17, 18), (18, 19), (19, 20),
    (5, 9), (9, 13), (13, 17),
]


@dataclass
class Landmark:
    x: float
    y: float


@dataclass
class HandGestureResult:
    handedness: str
    confidence: float
    finger_count: int
    fingers: list[int]
    gesture_name: str


@dataclass
class HandDetectionResult:
    hand_landmarks: list[list[Landmark]]
    hand_landmarks_px: list[np.ndarray]


HF_CDN_HOST = "cas-bridge.xethub.hf.co"


def _resolve_via_wlan0(hostname: str) -> str | None:
    try:
        proc = subprocess.run(
            ["resolvectl", "-i", "wlan0", "query", hostname],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None

    for line in proc.stdout.splitlines():
        if hostname in line:
            token = line.split(":", 1)[1].split("--", 1)[0].strip()
        else:
            token = line.split("--", 1)[0].strip()

        if token and ":" not in token and not token.startswith("192.168."):
            return token.split()[0]

    return None


def _download_via_wlan0(url: str, path: Path) -> None:
    parsed = urlparse(url)
    hostname = parsed.hostname
    if hostname is None:
        raise RuntimeError(f"Nieprawidlowy URL modelu: {url}")

    hf_ip = _resolve_via_wlan0(hostname)
    cdn_ip = _resolve_via_wlan0(HF_CDN_HOST)
    if hf_ip is None or cdn_ip is None:
        raise RuntimeError(
            "Nie udalo sie rozwiazac DNS przez wlan0. "
            "Router na end0 przechwytuje DNS (np. huggingface.co -> 192.168.31.1). "
            "Ustaw DNS na wlan0: sudo resolvectl dns wlan0 1.1.1.1 "
            "albo pobierz modele recznie do katalogu models/."
        )

    subprocess.run(
        [
            "curl",
            "-fsSL",
            "-L",
            "--resolve",
            f"{hostname}:443:{hf_ip}",
            "--resolve",
            f"{HF_CDN_HOST}:443:{cdn_ip}",
            "--interface",
            "wlan0",
            "-o",
            str(path),
            url,
        ],
        check=True,
    )


def _ensure_model(url: str, path: Path) -> Path:
    if path.exists() and path.stat().st_size > 100_000:
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Pobieram model ONNX do {path}...")
    _download_via_wlan0(url, path)
    return path


def _thumb_extended(landmarks, handedness: str, mirrored: bool) -> bool:
    label = handedness
    if mirrored and label in ("Left", "Right"):
        label = "Right" if label == "Left" else "Left"

    if label == "Right":
        return landmarks[4].x < landmarks[3].x
    if label == "Left":
        return landmarks[4].x > landmarks[3].x

    return landmarks[4].x > landmarks[2].x


def _landmark_dist(a, b) -> float:
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


def is_ok_gesture(landmarks) -> bool:
    hand_size = _landmark_dist(landmarks[0], landmarks[9])
    if hand_size == 0:
        return False

    thumb_index_dist = _landmark_dist(landmarks[4], landmarks[8])
    if thumb_index_dist > hand_size * 0.28:
        return False

    return all(
        landmarks[tip].y < landmarks[base].y
        for tip, base in ((12, 9), (16, 13), (20, 17))
    )


def count_fingers(landmarks, handedness: str = "Unknown", mirrored: bool = True) -> list[int]:
    fingers: list[int] = [_thumb_extended(landmarks, handedness, mirrored)]

    for tip, base in zip(FINGER_TIPS, FINGER_BASES):
        fingers.append(1 if landmarks[tip].y < landmarks[base].y else 0)

    if sum(fingers) == 4 and all(fingers[1:]):
        fingers[0] = 1

    return fingers


def gesture_name_for(fingers: list[int]) -> str:
    total = sum(fingers)
    thumb, index, middle, ring, pinky = fingers

    if total == 0:
        return "piesc"
    if total == 1:
        if index:
            return "wskazujacy"
        return "piesc"
    if total == 2:
        if index and middle:
            return "pokoj"
        return "dwa"
    if total == 3:
        return "trzy"
    if total == 4:
        return "cztery"
    if total == 5:
        return "otwarta_dlon"

    return "nieznany"


def _handedness_label(value: float) -> str:
    return "Left" if value <= 0.5 else "Right"


def _normalize_landmarks(landmarks_px: np.ndarray, width: int, height: int) -> list[Landmark]:
    return [
        Landmark(x=float(x) / width, y=float(y) / height)
        for x, y in landmarks_px[:, :2]
    ]


class HandGestureDetector:
    def __init__(
        self,
        max_hands: int = 2,
        min_detection_confidence: float = 0.7,
        min_tracking_confidence: float = 0.7,
        mirrored: bool = True,
    ):
        self.max_hands = max_hands
        self.mirrored = mirrored
        self._min_tracking_confidence = min_tracking_confidence

        palm_path = str(_ensure_model(PALM_MODEL_URL, PALM_MODEL_PATH))
        handpose_path = str(_ensure_model(HANDPOSE_MODEL_URL, HANDPOSE_MODEL_PATH))

        self._palm_detector = MPPalmDet(
            model_path=palm_path,
            score_threshold=min_detection_confidence * 0.85,
        )
        self._handpose_detector = MPHandPose(
            model_path=handpose_path,
            conf_threshold=min_detection_confidence,
        )

    def close(self) -> None:
        if self._palm_detector is None:
            return
        self._palm_detector = None
        self._handpose_detector = None

    def process(self, frame_bgr) -> tuple[list[HandGestureResult], HandDetectionResult]:
        height, width = frame_bgr.shape[:2]
        palms = self._palm_detector.infer(frame_bgr)

        if palms.shape[0] == 0:
            return [], HandDetectionResult(hand_landmarks=[], hand_landmarks_px=[])

        if palms.shape[0] > self.max_hands:
            order = np.argsort(palms[:, -1])[::-1][:self.max_hands]
            palms = palms[order]

        gestures: list[HandGestureResult] = []
        normalized_landmarks: list[list[Landmark]] = []
        pixel_landmarks: list[np.ndarray] = []

        for palm in palms:
            handpose = self._handpose_detector.infer(frame_bgr, palm)
            if handpose is None:
                continue

            landmarks_screen = handpose[4:67].reshape(21, 3)
            landmarks_px = landmarks_screen[:, :2].astype(np.int32)
            confidence = float(handpose[-1])
            label = _handedness_label(float(handpose[-2]))
            norm = _normalize_landmarks(landmarks_px, width, height)

            fingers = count_fingers(norm, label, self.mirrored)
            name = "ok" if is_ok_gesture(norm) else gesture_name_for(fingers)

            gestures.append(
                HandGestureResult(
                    handedness=label,
                    confidence=confidence,
                    finger_count=sum(fingers),
                    fingers=fingers,
                    gesture_name=name,
                )
            )
            normalized_landmarks.append(norm)
            pixel_landmarks.append(landmarks_px)

        return gestures, HandDetectionResult(
            hand_landmarks=normalized_landmarks,
            hand_landmarks_px=pixel_landmarks,
        )

    def draw(self, frame_bgr, results: HandDetectionResult) -> None:
        if not results.hand_landmarks_px:
            return

        for landmarks_px in results.hand_landmarks_px:
            for start, end in HAND_CONNECTIONS:
                x1, y1 = landmarks_px[start]
                x2, y2 = landmarks_px[end]
                cv2.line(frame_bgr, (x1, y1), (x2, y2), (0, 255, 0), 2)

            for x, y in landmarks_px:
                cv2.circle(frame_bgr, (int(x), int(y)), 4, (0, 0, 255), -1)

    def draw_command(self, frame_bgr, gesture: HandGestureResult | None) -> None:
        if gesture is None:
            label = "Gest: brak"
        elif gesture.gesture_name == "ok":
            label = "Gest: ok"
        else:
            label = f"Gest: {gesture.gesture_name} ({gesture.finger_count})"

        cv2.putText(
            frame_bgr,
            label,
            (10, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0),
            2,
        )
