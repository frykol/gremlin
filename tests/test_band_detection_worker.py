import unittest

from src.robot_state import RobotState, BandDetectionState
from src.workers.band_detection_worker import BandDetectionWorker
from src.hardware.band_detection.detector import BandDetectionResult


class FakeDetector:
    def __init__(self, results):
        self._results = list(results)

    def detect(self, image):
        return self._results.pop(0)


class BandDetectionWorkerTests(unittest.TestCase):
    def test_sets_both_detected_true_after_one_success(self):
        state = RobotState()
        state.last_frame = None
        detector = FakeDetector([BandDetectionResult(left=True, right=True, both=True)])
        worker = BandDetectionWorker(detector=detector, state=state, debounce_count=5)

        worker.process_frame(image=object())

        self.assertEqual(state.band_detection_state.both_detected, True)

    def test_stays_true_below_debounce_count_of_failures(self):
        state = RobotState()
        results = (
            [BandDetectionResult(left=True, right=True, both=True)]
            + [BandDetectionResult(left=False, right=False, both=False)] * 4
        )
        detector = FakeDetector(results)
        worker = BandDetectionWorker(detector=detector, state=state, debounce_count=5)

        for _ in range(5):
            worker.process_frame(image=object())

        self.assertEqual(state.band_detection_state.both_detected, True)

    def test_switches_to_false_after_debounce_count_of_consecutive_failures(self):
        state = RobotState()
        results = (
            [BandDetectionResult(left=True, right=True, both=True)]
            + [BandDetectionResult(left=False, right=False, both=False)] * 5
        )
        detector = FakeDetector(results)
        worker = BandDetectionWorker(detector=detector, state=state, debounce_count=5)

        for _ in range(6):
            worker.process_frame(image=object())

        self.assertEqual(state.band_detection_state.both_detected, False)


if __name__ == "__main__":
    unittest.main()
