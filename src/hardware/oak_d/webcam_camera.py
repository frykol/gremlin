import time
from typing import Optional

import cv2

from .interface import CameraInterface, CameraFrame


class WebcamCamera(CameraInterface):
    def __init__(
        self,
        device: int = 0,
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
        flip: bool = True,
    ):
        self.device = device
        self.width = width
        self.height = height
        self.fps = fps
        self.flip = flip
        self.frame_id = 0
        self.running = False
        self.cap: cv2.VideoCapture | None = None

    def start(self) -> None:
        if self.running:
            return

        self.cap = cv2.VideoCapture(self.device)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)

        if not self.cap.isOpened():
            raise RuntimeError(f"Nie można otworzyć kamery (device={self.device})")

        self.running = True
        print(f"Kamera laptopa działa (device={self.device}, {self.width}x{self.height})")

    def stop(self) -> None:
        self.running = False
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        print("Kamera laptopa zatrzymana")

    def get_camera_frame(self) -> Optional[CameraFrame]:
        if not self.running or self.cap is None:
            return None

        ok, frame = self.cap.read()
        if not ok:
            return None

        if self.flip:
            frame = cv2.flip(frame, 1)

        self.frame_id += 1
        return CameraFrame(
            image=frame,
            timestamp=time.time(),
            width=frame.shape[1],
            height=frame.shape[0],
            frame_id=self.frame_id,
        )
