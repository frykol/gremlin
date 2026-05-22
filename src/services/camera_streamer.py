import json
import base64
import asyncio
import cv2

from src.dev_connection.interface import WSClientInterface
from src.robot_state import RobotState

class CameraStreamer:
    def __init__(self,ws: WSClientInterface, state: RobotState, fps: int = 15):
        #self.camera = camera
        self.ws: WSClientInterface = ws
        self.state: RobotState = state
        self.fps: int = fps

    async def run(self):
        delay = 1 / self.fps

        while True:
            if self.state.stream_enabled:
                await self.send_camera_frame()

            await asyncio.sleep(delay)

    async def send_camera_frame(self):
        frame = self.state.last_frame

        if frame is None:
            return

        ok, buffer = cv2.imencode(
            ".jpg",
            frame.image,
            [cv2.IMWRITE_JPEG_QUALITY, 70]
        )

        if not ok:
            return

        jpg_base64 = base64.b64encode(buffer).decode("utf-8")

        await self.ws.send(json.dumps({
            "type": "camera_frame",
            "image": jpg_base64,
            "timestamp": frame.timestamp,
            "width": frame.width,
            "height": frame.height,
            "frame_id": frame.frame_id
        }))