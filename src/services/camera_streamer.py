import json
import base64
import asyncio
import cv2

from src.dev_connection.interface import WSClientInterface
from src.robot_state import RobotState

class CameraStreamer:
    def __init__(
        self,
        ws: WSClientInterface,
        state: RobotState,
        fps: int = 15,
        flip_vertical: bool = False,
        overlay_gestures: bool = False,
    ):
        self.ws: WSClientInterface = ws
        self.state: RobotState = state
        self.fps: int = fps
        self.flip_vertical = flip_vertical
        self.overlay_gestures = overlay_gestures

    async def run(self):
        delay = 1 / self.fps

        while True:
            if self.state.stream_enabled:
                await self.send_camera_frame()

            await asyncio.sleep(delay)

    def _prepare_stream_image(self):
        frame = self.state.last_frame
        if frame is None:
            return None

        if self.overlay_gestures and self.state.display_frame is not None:
            image = self.state.display_frame.copy()
        else:
            image = frame.image.copy()
            if self.flip_vertical:
                image = cv2.flip(image, 0)

        return image

    async def send_camera_frame(self):
        image = self._prepare_stream_image()
        if image is None:
            return

        ok, buffer = cv2.imencode(
            ".jpg",
            image,
            [cv2.IMWRITE_JPEG_QUALITY, 70]
        )

        if not ok:
            return

        jpg_base64 = base64.b64encode(buffer).decode("utf-8")

        frame = self.state.last_frame
        await self.ws.send(json.dumps({
            "type": "camera_frame",
            "image": jpg_base64,
            "timestamp": frame.timestamp,
            "width": image.shape[1],
            "height": image.shape[0],
            "frame_id": frame.frame_id
        }))