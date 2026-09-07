import asyncio
import time
import unittest

from src.hardware.oak_d.interface import CameraFrame
from src.logic.robot_logic import RobotLogic
from src.robot_state import ColorDetectionState, RobotState

MOTOR_PAIRS = {"FL": (0, 1), "FR": (3, 2), "RL": (4, 5), "RR": (7, 6)}


class DummyI2cPwm:
    def __init__(self):
        self.calls = []

    def set_pwm(self, channel, on, off):
        self.calls.append((channel, off))


def make_frame(width=200):
    return CameraFrame(image=None, timestamp=time.time(), width=width, height=100, frame_id=0)


class TickFollowBandTests(unittest.TestCase):
    def test_drives_when_band_freshly_detected(self):
        state = RobotState(
            follow_band_mode=True,
            follow_band_max_pwm=1000,
            last_frame=make_frame(),
            color_detection_state=ColorDetectionState(
                green_on_yellow_detected=True, target_bbox=(90, 0, 20, 50), last_update=time.time()
            ),
        )
        i2c_pwm = DummyI2cPwm()
        logic = RobotLogic(gpio=None, i2c_pwm=i2c_pwm, state=state, motor_pairs=MOTOR_PAIRS)

        logic._tick_follow_band()

        self.assertTrue(any(off != 0 for _ch, off in i2c_pwm.calls))

    def test_stops_when_detection_is_stale(self):
        state = RobotState(
            follow_band_mode=True,
            follow_band_max_pwm=1000,
            last_frame=make_frame(),
            color_detection_state=ColorDetectionState(
                green_on_yellow_detected=True, target_bbox=(90, 0, 20, 50), last_update=time.time() - 5.0
            ),
        )
        i2c_pwm = DummyI2cPwm()
        logic = RobotLogic(gpio=None, i2c_pwm=i2c_pwm, state=state, motor_pairs=MOTOR_PAIRS)
        logic._was_following = True

        logic._tick_follow_band()

        self.assertTrue(all(off == 0 for _ch, off in i2c_pwm.calls))
        self.assertFalse(logic._was_following)

    def test_stops_when_band_not_detected(self):
        state = RobotState(
            follow_band_mode=True,
            follow_band_max_pwm=1000,
            last_frame=make_frame(),
            color_detection_state=ColorDetectionState(
                green_on_yellow_detected=False, target_bbox=(90, 0, 20, 50), last_update=time.time()
            ),
        )
        i2c_pwm = DummyI2cPwm()
        logic = RobotLogic(gpio=None, i2c_pwm=i2c_pwm, state=state, motor_pairs=MOTOR_PAIRS)
        logic._was_following = True

        logic._tick_follow_band()

        self.assertTrue(all(off == 0 for _ch, off in i2c_pwm.calls))

    def test_no_pwm_calls_when_no_prior_movement_and_no_detection(self):
        state = RobotState(follow_band_mode=True, follow_band_max_pwm=1000)
        i2c_pwm = DummyI2cPwm()
        logic = RobotLogic(gpio=None, i2c_pwm=i2c_pwm, state=state, motor_pairs=MOTOR_PAIRS)

        logic._tick_follow_band()

        self.assertEqual(i2c_pwm.calls, [])


class RunLoopTests(unittest.TestCase):
    def test_stops_once_when_follow_mode_turned_off_mid_drive(self):
        async def run_test():
            state = RobotState(follow_band_mode=False)
            i2c_pwm = DummyI2cPwm()
            logic = RobotLogic(gpio=None, i2c_pwm=i2c_pwm, state=state, motor_pairs=MOTOR_PAIRS)
            logic._was_following = True

            task = asyncio.create_task(logic.run())
            await asyncio.sleep(0.15)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            self.assertTrue(all(off == 0 for _ch, off in i2c_pwm.calls))
            self.assertFalse(logic._was_following)

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
