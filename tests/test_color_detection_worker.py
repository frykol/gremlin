import unittest

import numpy as np

from src.robot_state import RobotState
from src.workers.color_detection_worker import ColorDetectionWorker


def make_solid_bgr_image(width, height, bgr_color):
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :] = bgr_color
    return image


class ColorDetectionWorkerTests(unittest.TestCase):
    def test_detects_blue_frame(self):
        state = RobotState()
        image = make_solid_bgr_image(50, 50, (255, 0, 0))
        worker = ColorDetectionWorker(state=state, blue_ratio_threshold=0.5)

        worker.process_frame(image)

        self.assertTrue(state.color_detection_state.detected)
        self.assertGreater(state.color_detection_state.blue_ratio, 0.9)

    def test_does_not_detect_non_blue_frame(self):
        state = RobotState()
        image = make_solid_bgr_image(50, 50, (0, 0, 255))
        worker = ColorDetectionWorker(state=state, blue_ratio_threshold=0.5)

        worker.process_frame(image)

        self.assertFalse(state.color_detection_state.detected)
        self.assertEqual(state.color_detection_state.blue_ratio, 0.0)


if __name__ == "__main__":
    unittest.main()
