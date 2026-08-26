import unittest

import numpy as np

from src.hardware.color_detection.color_detector import is_band_present


def make_solid_bgr_image(width, height, bgr_color):
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :] = bgr_color
    return image


class IsBandPresentTests(unittest.TestCase):
    def test_returns_true_for_fully_blue_roi(self):
        image = make_solid_bgr_image(100, 100, (255, 0, 0))  # BGR blue

        result = is_band_present(image, center=(50, 50), roi_half_size=10)

        self.assertTrue(result)

    def test_returns_false_for_skin_tone_roi(self):
        image = make_solid_bgr_image(100, 100, (120, 170, 220))  # BGR skin tone

        result = is_band_present(image, center=(50, 50), roi_half_size=10)

        self.assertFalse(result)

    def test_returns_false_when_center_is_none(self):
        image = make_solid_bgr_image(100, 100, (255, 0, 0))

        result = is_band_present(image, center=None, roi_half_size=10)

        self.assertFalse(result)

    def test_handles_roi_clipped_at_image_edge(self):
        image = make_solid_bgr_image(100, 100, (255, 0, 0))

        result = is_band_present(image, center=(0, 0), roi_half_size=10)

        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
