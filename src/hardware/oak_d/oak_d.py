import time
from typing import Optional

import cv2
import depthai as dai

from .interface import CameraInterface, CameraFrame

class OakDCamera(CameraInterface):
    def __init__(self, width=640, height=480, fps=30):
        self.width = width
        self.height = height
        self.fps = fps

        self.running = False

        self.pipeline = None
        self.device = None
        self.queue = None

    def start(self) -> None:
        if self.running:
            return

        self.pipeline = dai.Pipeline()

        cam_rgb = self.pipeline.create(dai.node.ColorCamera)
        xout_rgb = self.pipeline.create(dai.node.XLinkOut)

        xout_rgb.setStreamName("rgb")

        cam_rgb.setPreviewSize(self.width, self.height)
        cam_rgb.setInterleaved(False)
        cam_rgb.setColorOrder(dai.ColorCameraProperties.ColorOrder.BGR)
        cam_rgb.setFps(self.fps)

        cam_rgb.preview.link(xout_rgb.input)

        self.device = dai.Device(self.pipeline)
        self.queue = self.device.getOutputQueue(
            name="rgb",
            maxSize=4,
            blocking=False
        )

        self.running = True

        print("OAK-D kamera działa")

    def stop(self) -> None:
        self.running = False

        if self.device is not None:
            self.device.close()

        print("OAK-D kamera zatrzymana")

    def get_camera_frame(self) -> Optional[CameraFrame]:
        if not self.running:
            return None

        in_rgb = self.queue.tryGet()

        if in_rgb is None:
            return None

        frame = in_rgb.getCvFrame()

        return CameraFrame(
            image=frame,
            timestamp=time.time(),
            width=self.width,
            height=self.height,
            frame_id=0
        )