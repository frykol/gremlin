import unittest

import numpy as np

from src.hardware.color_detection.color_detector import (
    any_bbox_intersects,
    bboxes_intersect,
    blue_mask,
    find_blue_bboxes,
    find_bbox_on_background,
    is_band_present,
)


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


class FindBlueBboxesTests(unittest.TestCase):
    def test_returns_empty_list_for_no_blue(self):
        image = make_solid_bgr_image(100, 100, (0, 0, 255))
        mask = blue_mask(image)

        self.assertEqual(find_blue_bboxes(mask), [])

    def test_finds_single_blob(self):
        image = make_solid_bgr_image(100, 100, (0, 0, 255))
        image[20:40, 20:40] = (255, 0, 0)
        mask = blue_mask(image)

        boxes = find_blue_bboxes(mask, min_area_px=50)

        self.assertEqual(len(boxes), 1)
        x, y, w, h = boxes[0]
        self.assertAlmostEqual(x, 20, delta=1)
        self.assertAlmostEqual(y, 20, delta=1)
        self.assertAlmostEqual(w, 20, delta=1)
        self.assertAlmostEqual(h, 20, delta=1)

    def test_finds_multiple_separate_blobs_largest_first(self):
        image = make_solid_bgr_image(100, 100, (0, 0, 255))
        image[10:20, 10:20] = (255, 0, 0)  # small blob, 10x10
        image[60:90, 60:90] = (255, 0, 0)  # large blob, 30x30
        mask = blue_mask(image)

        boxes = find_blue_bboxes(mask, min_area_px=50)

        self.assertEqual(len(boxes), 2)
        self.assertGreater(boxes[0][2] * boxes[0][3], boxes[1][2] * boxes[1][3])

    def test_ignores_blobs_below_min_area(self):
        image = make_solid_bgr_image(100, 100, (0, 0, 255))
        image[10:15, 10:15] = (255, 0, 0)  # 5x5 = 25px, below threshold
        mask = blue_mask(image)

        boxes = find_blue_bboxes(mask, min_area_px=150)

        self.assertEqual(boxes, [])

    def test_rejects_taller_than_wide_blob_by_default(self):
        image = make_solid_bgr_image(100, 100, (0, 0, 255))
        image[10:50, 10:25] = (255, 0, 0)  # 15 wide x 40 tall - vertical blob

        boxes = find_blue_bboxes(blue_mask(image), min_area_px=50)

        self.assertEqual(boxes, [])

    def test_keeps_wider_than_tall_blob(self):
        image = make_solid_bgr_image(100, 100, (0, 0, 255))
        image[10:25, 10:60] = (255, 0, 0)  # 50 wide x 15 tall - horizontal blob

        boxes = find_blue_bboxes(blue_mask(image), min_area_px=50)

        self.assertEqual(len(boxes), 1)

    def test_require_horizontal_false_keeps_vertical_blob(self):
        image = make_solid_bgr_image(100, 100, (0, 0, 255))
        image[10:50, 10:25] = (255, 0, 0)  # vertical blob

        boxes = find_blue_bboxes(blue_mask(image), min_area_px=50, require_horizontal=False)

        self.assertEqual(len(boxes), 1)

    def test_min_aspect_ratio_rejects_blob_below_ratio(self):
        image = make_solid_bgr_image(100, 100, (0, 0, 255))
        image[10:25, 10:35] = (255, 0, 0)  # 25 wide x 15 tall - ratio 1.67, below 2.0

        boxes = find_blue_bboxes(blue_mask(image), min_area_px=50, min_aspect_ratio=2.0)

        self.assertEqual(boxes, [])

    def test_min_aspect_ratio_keeps_blob_at_or_above_ratio(self):
        image = make_solid_bgr_image(100, 100, (0, 0, 255))
        image[10:25, 10:50] = (255, 0, 0)  # 40 wide x 15 tall - ratio 2.67, above 2.0

        boxes = find_blue_bboxes(blue_mask(image), min_area_px=50, min_aspect_ratio=2.0)

        self.assertEqual(len(boxes), 1)

    def test_min_rectangularity_rejects_non_rectangular_shape(self):
        image = make_solid_bgr_image(100, 100, (0, 0, 255))
        cv2_circle_image = image.copy()
        import cv2 as _cv2
        _cv2.circle(cv2_circle_image, (50, 50), 20, (255, 0, 0), thickness=-1)

        boxes = find_blue_bboxes(blue_mask(cv2_circle_image), min_area_px=50, min_rectangularity=0.9)

        self.assertEqual(boxes, [])

    def test_min_rectangularity_keeps_solid_rectangle(self):
        image = make_solid_bgr_image(100, 100, (0, 0, 255))
        image[10:30, 10:50] = (255, 0, 0)  # solid filled rectangle, rectangularity ~1.0

        boxes = find_blue_bboxes(blue_mask(image), min_area_px=50, min_rectangularity=0.9)

        self.assertEqual(len(boxes), 1)


class BboxesIntersectTests(unittest.TestCase):
    def test_returns_true_for_overlapping_boxes(self):
        self.assertTrue(bboxes_intersect((0, 0, 10, 10), (5, 5, 10, 10)))

    def test_returns_false_for_disjoint_boxes(self):
        self.assertFalse(bboxes_intersect((0, 0, 10, 10), (20, 20, 10, 10)))

    def test_returns_true_when_one_contains_the_other(self):
        self.assertTrue(bboxes_intersect((0, 0, 100, 100), (10, 10, 5, 5)))

    def test_returns_false_for_touching_edges(self):
        self.assertFalse(bboxes_intersect((0, 0, 10, 10), (10, 0, 10, 10)))


class AnyBboxIntersectsTests(unittest.TestCase):
    def test_returns_false_when_target_is_none(self):
        self.assertFalse(any_bbox_intersects(None, [(0, 0, 10, 10)]))

    def test_returns_false_when_no_candidate_overlaps(self):
        self.assertFalse(any_bbox_intersects((0, 0, 10, 10), [(50, 50, 10, 10)]))

    def test_returns_true_when_a_candidate_overlaps(self):
        self.assertTrue(any_bbox_intersects((0, 0, 10, 10), [(50, 50, 10, 10), (5, 5, 10, 10)]))


class FindBboxOnBackgroundTests(unittest.TestCase):
    def test_returns_none_when_no_foreground_boxes(self):
        self.assertIsNone(find_bbox_on_background([], [(0, 0, 100, 100)]))

    def test_returns_none_when_no_overlap(self):
        result = find_bbox_on_background([(0, 0, 10, 10)], [(50, 50, 10, 10)])
        self.assertIsNone(result)

    def test_returns_matching_foreground_box(self):
        green = (5, 5, 10, 10)
        yellow = (0, 0, 20, 20)
        result = find_bbox_on_background([green], [yellow])
        self.assertEqual(result, green)

    def test_returns_first_foreground_box_that_overlaps_any_background(self):
        green_no_overlap = (100, 100, 10, 10)
        green_overlap = (5, 5, 10, 10)
        yellow = (0, 0, 20, 20)
        result = find_bbox_on_background([green_no_overlap, green_overlap], [yellow])
        self.assertEqual(result, green_overlap)


if __name__ == "__main__":
    unittest.main()
