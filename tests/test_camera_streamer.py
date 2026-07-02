import sys
import types
import unittest

cv2_stub = types.ModuleType("cv2")
cv2_stub.IMWRITE_JPEG_QUALITY = 1
cv2_stub.imencode = lambda *args, **kwargs: (True, b"")
cv2_stub.resize = lambda frame, size, interpolation=None: frame
sys.modules.setdefault("cv2", cv2_stub)

numpy_stub = types.ModuleType("numpy")
numpy_stub.ndarray = object
sys.modules.setdefault("numpy", numpy_stub)

from src.robot_state import RobotState
from src.services.camera_streamer import CameraStreamer


class DummyUdpSender:
    def __init__(self):
        self.frames = []

    def send_frame(self, frame_id, timestamp, payload):
        self.frames.append((frame_id, timestamp, payload))


class CameraStreamerTests(unittest.TestCase):
    def test_calculate_target_dimensions_downscales_large_images(self):
        streamer = CameraStreamer(
            udp_sender=DummyUdpSender(),
            state=RobotState(),
            max_frame_width=320,
            max_frame_height=240,
        )

        width, height = streamer._calculate_target_dimensions(1000, 1000)

        self.assertLessEqual(height, 240)
        self.assertLessEqual(width, 320)


if __name__ == "__main__":
    unittest.main()
