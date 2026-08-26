import os
import urllib.request

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

from .interface import AnklePositions, PoseEstimatorInterface

# mediapipe>=1.0 dropped the legacy mp.solutions.pose API (only available as
# the aarch64/py3.13 wheel on this device) in favor of the Tasks API, which
# needs a model bundle downloaded separately instead of being bundled in pip.
DEFAULT_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
)
DEFAULT_MODEL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "pose_landmarker_lite.task"
)

LEFT_ANKLE_LANDMARK_INDEX = 27
RIGHT_ANKLE_LANDMARK_INDEX = 28
MIN_LANDMARK_VISIBILITY = 0.5


def ensure_model_downloaded(model_path: str, model_url: str) -> str:
    if os.path.exists(model_path):
        return model_path

    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    tmp_path = f"{model_path}.tmp"
    urllib.request.urlretrieve(model_url, tmp_path)
    os.replace(tmp_path, model_path)

    return model_path


class MediaPipePoseEstimator(PoseEstimatorInterface):
    def __init__(
        self,
        model_path: str = DEFAULT_MODEL_PATH,
        model_url: str = DEFAULT_MODEL_URL,
    ):
        resolved_model_path = ensure_model_downloaded(model_path, model_url)

        options = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=resolved_model_path),
            running_mode=vision.RunningMode.IMAGE,
            num_poses=1,
        )
        self._landmarker = vision.PoseLandmarker.create_from_options(options)

    def get_ankle_positions(self, image: np.ndarray) -> AnklePositions:
        height, width = image.shape[:2]

        rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_image)

        result = self._landmarker.detect(mp_image)

        if not result.pose_landmarks:
            return AnklePositions(left=None, right=None)

        landmarks = result.pose_landmarks[0]

        return AnklePositions(
            left=self._landmark_to_point(landmarks[LEFT_ANKLE_LANDMARK_INDEX], width, height),
            right=self._landmark_to_point(landmarks[RIGHT_ANKLE_LANDMARK_INDEX], width, height),
        )

    @staticmethod
    def _landmark_to_point(landmark, width: int, height: int):
        if landmark.visibility < MIN_LANDMARK_VISIBILITY:
            return None

        return (int(landmark.x * width), int(landmark.y * height))

    def close(self) -> None:
        self._landmarker.close()
