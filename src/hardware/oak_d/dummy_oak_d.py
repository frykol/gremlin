import time
import numpy as np

from .interface import CameraInterface, CameraFrame
from typing import Optional

class FakeOakDCamera(CameraInterface):
    def __init__(self, width = 640, height = 480):
        self.width = width
        self.height = height
        self.running = False
        self.counter = 0

    def start(self) -> None:
       self.running = True 
       print("Kamera dziala")

    def stop(self) -> None:
        self.running = False
        print("Kamera nie dziala")


    def get_camera_frame(self) -> Optional[CameraFrame]:
        if not self.running:
            return

        self.counter += 1

        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        x = (self.counter * 10) % self.width
        frame[:, x:x + 20] = 255

        return CameraFrame(image=frame, timestamp=time.time())
