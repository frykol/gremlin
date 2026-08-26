import unittest

import numpy as np

from src.hardware.band_detection.detector import BandDetectionResult, BandDetector
from src.hardware.band_detection.interface import AnklePositions, PoseEstimatorInterface


def make_solid_bgr_image(width, height, bgr_color):
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :] = bgr_color
    return image


class FakePoseEstimator(PoseEstimatorInterface):
    def __init__(self, ankle_positions: AnklePositions):
        self.ankle_positions = ankle_positions

    def get_ankle_positions(self, image):
        return self.ankle_positions


class BandDetectorTests(unittest.TestCase):
    def test_detects_both_bands_when_both_ankles_blue(self):
        image = make_solid_bgr_image(100, 100, (255, 0, 0))
        pose_estimator = FakePoseEstimator(AnklePositions(left=(20, 80), right=(80, 80)))
        detector = BandDetector(pose_estimator=pose_estimator, roi_half_size=10)

        result = detector.detect(image)

        self.assertTrue(result.left)
        self.assertTrue(result.right)
        self.assertTrue(result.both)

    def test_both_false_when_no_pose_detected(self):
        image = make_solid_bgr_image(100, 100, (255, 0, 0))
        pose_estimator = FakePoseEstimator(AnklePositions(left=None, right=None))
        detector = BandDetector(pose_estimator=pose_estimator, roi_half_size=10)

        result = detector.detect(image)

        self.assertEqual(result, BandDetectionResult(left=False, right=False, both=False))

    def test_both_false_when_only_one_ankle_has_band(self):
        image = make_solid_bgr_image(100, 100, (255, 0, 0))
        image[70:90, 70:90] = (0, 0, 255)  # right ankle area is red, not blue
        pose_estimator = FakePoseEstimator(AnklePositions(left=(20, 80), right=(80, 80)))
        detector = BandDetector(pose_estimator=pose_estimator, roi_half_size=10)

        result = detector.detect(image)

        self.assertTrue(result.left)
        self.assertFalse(result.right)
        self.assertFalse(result.both)


if __name__ == "__main__":
    unittest.main()
