from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlretrieve

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.vision import HandLandmarksConnections

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
)
MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "hand_landmarker.task"

FINGER_TIPS = [8, 12, 16, 20]
FINGER_BASES = [5, 9, 13, 17]


@dataclass
class HandGestureResult:
    handedness: str
    confidence: float
    finger_count: int
    fingers: list[int]
    gesture_name: str


def _ensure_model() -> Path:
    if MODEL_PATH.exists():
        return MODEL_PATH

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f"Pobieram model MediaPipe do {MODEL_PATH}...")
    urlretrieve(MODEL_URL, MODEL_PATH)
    return MODEL_PATH


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


class HandGestureDetector:
    def __init__(
        self,
        max_hands: int = 2,
        min_detection_confidence: float = 0.7,
        min_tracking_confidence: float = 0.7,
        mirrored: bool = True,
    ):
        self.mirrored = mirrored
        options = vision.HandLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(_ensure_model())),
            running_mode=vision.RunningMode.IMAGE,
            num_hands=max_hands,
            min_hand_detection_confidence=min_detection_confidence,
            min_hand_presence_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)

    def close(self) -> None:
        self._landmarker.close()

    def process(self, frame_bgr) -> tuple[list[HandGestureResult], vision.HandLandmarkerResult]:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        results = self._landmarker.detect(mp_image)

        gestures: list[HandGestureResult] = []
        if not results.hand_landmarks:
            return gestures, results

        for index, hand_landmarks in enumerate(results.hand_landmarks):
            label = "Unknown"
            confidence = 1.0
            if results.handedness and index < len(results.handedness):
                category = results.handedness[index][0]
                label = category.category_name
                confidence = category.score

            fingers = count_fingers(hand_landmarks, label, self.mirrored)
            if is_ok_gesture(hand_landmarks):
                name = "ok"
            else:
                name = gesture_name_for(fingers)

            gestures.append(
                HandGestureResult(
                    handedness=label,
                    confidence=confidence,
                    finger_count=sum(fingers),
                    fingers=fingers,
                    gesture_name=name,
                )
            )

        return gestures, results

    def draw(self, frame_bgr, results: vision.HandLandmarkerResult) -> None:
        if not results.hand_landmarks:
            return

        height, width = frame_bgr.shape[:2]

        for hand_landmarks in results.hand_landmarks:
            for connection in HandLandmarksConnections.HAND_CONNECTIONS:
                start = hand_landmarks[connection.start]
                end = hand_landmarks[connection.end]
                x1, y1 = int(start.x * width), int(start.y * height)
                x2, y2 = int(end.x * width), int(end.y * height)
                cv2.line(frame_bgr, (x1, y1), (x2, y2), (0, 255, 0), 2)

            for landmark in hand_landmarks:
                x, y = int(landmark.x * width), int(landmark.y * height)
                cv2.circle(frame_bgr, (x, y), 4, (0, 0, 255), -1)

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
