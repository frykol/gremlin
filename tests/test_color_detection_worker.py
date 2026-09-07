import unittest

import numpy as np

from src.robot_state import RobotState
from src.workers.color_detection_worker import ColorDetectionWorker


def make_solid_bgr_image(width, height, bgr_color):
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :] = bgr_color
    return image


BLUE_BGR = (255, 0, 0)
RED_BGR = (0, 0, 255)
YELLOW_BGR = (0, 255, 255)


class ColorDetectionWorkerTests(unittest.TestCase):
    def test_detects_blue_frame(self):
        state = RobotState()
        image = make_solid_bgr_image(50, 50, BLUE_BGR)
        worker = ColorDetectionWorker(state=state, blue_ratio_threshold=0.5)

        worker.process_frame(image)

        self.assertTrue(state.color_detection_state.detected)
        self.assertGreater(state.color_detection_state.blue_ratio, 0.9)

    def test_does_not_detect_non_blue_frame(self):
        state = RobotState()
        image = make_solid_bgr_image(50, 50, RED_BGR)
        worker = ColorDetectionWorker(state=state, blue_ratio_threshold=0.5)

        worker.process_frame(image)

        self.assertFalse(state.color_detection_state.detected)
        self.assertEqual(state.color_detection_state.blue_ratio, 0.0)

    def test_finds_multiple_blue_blob_bboxes(self):
        state = RobotState()
        image = make_solid_bgr_image(100, 100, RED_BGR)
        image[10:25, 10:50] = BLUE_BGR  # 40 wide x 15 tall, ratio 2.67
        image[60:75, 55:95] = BLUE_BGR  # 40 wide x 15 tall, ratio 2.67
        worker = ColorDetectionWorker(state=state, blue_ratio_threshold=0.9, min_blob_area_px=50)

        worker.process_frame(image)

        self.assertEqual(len(state.color_detection_state.blue_bboxes), 2)

    def test_blue_bboxes_empty_when_no_blue(self):
        state = RobotState()
        image = make_solid_bgr_image(50, 50, RED_BGR)
        worker = ColorDetectionWorker(state=state, blue_ratio_threshold=0.5)

        worker.process_frame(image)

        self.assertEqual(state.color_detection_state.blue_bboxes, [])

    def test_finds_yellow_bboxes(self):
        state = RobotState()
        image = make_solid_bgr_image(100, 100, RED_BGR)
        image[10:30, 10:30] = YELLOW_BGR
        worker = ColorDetectionWorker(state=state, min_blob_area_px=50)

        worker.process_frame(image)

        self.assertEqual(len(state.color_detection_state.yellow_bboxes), 1)

    def test_green_on_yellow_detected_when_blue_blob_overlaps_yellow_blob(self):
        state = RobotState()
        image = make_solid_bgr_image(100, 100, RED_BGR)
        image[10:60, 10:60] = YELLOW_BGR  # yellow background patch
        image[25:35, 15:55] = BLUE_BGR  # 40 wide x 10 tall marker (ratio 4.0) on the yellow patch
        worker = ColorDetectionWorker(state=state, min_blob_area_px=50)

        worker.process_frame(image)

        self.assertTrue(state.color_detection_state.green_on_yellow_detected)
        self.assertEqual(state.color_detection_state.target_bbox, (15, 25, 40, 10))

    def test_green_on_yellow_not_detected_when_no_yellow_overlap(self):
        state = RobotState()
        image = make_solid_bgr_image(100, 100, RED_BGR)
        image[10:30, 10:30] = YELLOW_BGR
        image[60:80, 60:80] = BLUE_BGR  # marker far from the yellow patch
        worker = ColorDetectionWorker(state=state, min_blob_area_px=50)

        worker.process_frame(image)

        self.assertFalse(state.color_detection_state.green_on_yellow_detected)
        self.assertIsNone(state.color_detection_state.target_bbox)

    def test_green_on_yellow_not_detected_when_no_yellow_at_all(self):
        state = RobotState()
        image = make_solid_bgr_image(100, 100, RED_BGR)
        image[20:40, 20:40] = BLUE_BGR
        worker = ColorDetectionWorker(state=state, min_blob_area_px=50)

        worker.process_frame(image)

        self.assertFalse(state.color_detection_state.green_on_yellow_detected)
        self.assertIsNone(state.color_detection_state.target_bbox)


if __name__ == "__main__":
    unittest.main()
