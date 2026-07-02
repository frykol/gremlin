import asyncio
import cv2

from src.dev_connection.udp_frame_sender import UdpFrameSender
from src.robot_state import RobotState


class CameraStreamer:
    def __init__(
        self,
        udp_sender: UdpFrameSender,
        state: RobotState,
        fps: int = 15,
        max_frame_width: int = 640,
        max_frame_height: int = 480,
        jpeg_quality: int = 55,
    ):
        self.udp_sender: UdpFrameSender = udp_sender
        self.state: RobotState = state
        self.fps: int = fps
        self.max_frame_width: int = max_frame_width
        self.max_frame_height: int = max_frame_height
        self.jpeg_quality: int = jpeg_quality
        self._sending_frame: bool = False
        self._last_sent_at: float = 0.0

    async def run(self):
        min_interval = max(0.001, 1 / self.fps) if self.fps > 0 else 0.001

        while True:
            now = asyncio.get_running_loop().time()

            should_send = (
                self.state.stream_enabled
                and self.state.last_frame is not None
                and not self._sending_frame
                and (now - self._last_sent_at) >= min_interval
            )

            if should_send:
                self._last_sent_at = now
                self._sending_frame = True
                try:
                    await self.send_camera_frame()
                finally:
                    self._sending_frame = False

            await asyncio.sleep(0.001)

    def _calculate_target_dimensions(self, width: int, height: int):
        if width <= 0 or height <= 0:
            return width, height

        scale_width = self.max_frame_width / width if self.max_frame_width > 0 else 1.0
        scale_height = self.max_frame_height / height if self.max_frame_height > 0 else 1.0
        scale = min(1.0, scale_width, scale_height)

        if scale >= 1.0:
            return width, height

        return max(1, int(width * scale)), max(1, int(height * scale))

    def _prepare_frame_for_stream(self, frame):
        height, width = frame.shape[:2]
        target_width, target_height = self._calculate_target_dimensions(width, height)

        if (target_width, target_height) != (width, height):
            frame = cv2.resize(
                frame,
                (target_width, target_height),
                interpolation=cv2.INTER_AREA,
            )

        return frame

    async def send_camera_frame(self):
        frame = self.state.last_frame

        if frame is None:
            return

        prepared_frame = self._prepare_frame_for_stream(frame.image)

        ok, buffer = cv2.imencode(
            ".jpg",
            prepared_frame,
            [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
        )

        if not ok:
            return

        self.udp_sender.send_frame(frame.frame_id, frame.timestamp, buffer.tobytes())