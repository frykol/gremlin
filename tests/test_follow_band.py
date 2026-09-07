import unittest

from src.logic.follow_band import compute_follow_pwm, compute_follow_vector, stop_pwm

MOTOR_PAIRS = {"FL": (0, 1), "FR": (3, 2), "RL": (4, 5), "RR": (7, 6)}


class ComputeFollowVectorTests(unittest.TestCase):
    def test_centered_bbox_drives_straight_forward(self):
        vy, omega = compute_follow_vector((90, 0, 20, 50), frame_width=200)  # center at x=100

        self.assertAlmostEqual(omega, 0.0, places=3)
        self.assertAlmostEqual(vy, 1.0, places=3)

    def test_bbox_left_of_center_turns_left_negative_omega(self):
        vy, omega = compute_follow_vector((0, 0, 20, 50), frame_width=200)  # center at x=10

        self.assertLess(omega, 0.0)
        self.assertLess(vy, 1.0)

    def test_bbox_right_of_center_turns_right_positive_omega(self):
        vy, omega = compute_follow_vector((180, 0, 20, 50), frame_width=200)  # center at x=190

        self.assertGreater(omega, 0.0)
        self.assertLess(vy, 1.0)

    def test_zero_frame_width_returns_zero_vector(self):
        self.assertEqual(compute_follow_vector((0, 0, 10, 10), frame_width=0), (0.0, 0.0))


class ComputeFollowPwmTests(unittest.TestCase):
    def test_centered_target_drives_all_wheels_forward(self):
        values = compute_follow_pwm((90, 0, 20, 50), frame_width=200, max_pwm=1000, motor_pairs=MOTOR_PAIRS)

        # FORWARD_SIGN is negative (mirrors control.js DIRECTIONS['Przód']),
        # so "drive forward" activates each pair's second (index-1) channel.
        self.assertEqual(values[0], 0)
        self.assertEqual(values[1], 1000)  # FL forward
        self.assertEqual(values[3], 0)
        self.assertEqual(values[2], 1000)  # FR forward

    def test_target_far_right_turns_in_place(self):
        values = compute_follow_pwm((196, 0, 20, 50), frame_width=200, max_pwm=1000, motor_pairs=MOTOR_PAIRS)

        self.assertGreater(values[0], 0)  # FL channel 0
        self.assertGreater(values[2], 0)  # FR channel 2

    def test_uses_provided_motor_pairs_channels(self):
        values = compute_follow_pwm((90, 0, 20, 50), frame_width=200, max_pwm=500, motor_pairs=MOTOR_PAIRS)

        self.assertEqual(set(values.keys()), {0, 1, 2, 3, 4, 5, 6, 7})


class StopPwmTests(unittest.TestCase):
    def test_returns_zero_for_all_configured_channels(self):
        values = stop_pwm(MOTOR_PAIRS)

        self.assertEqual(values, {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0})


if __name__ == "__main__":
    unittest.main()
