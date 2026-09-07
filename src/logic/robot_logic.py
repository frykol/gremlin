import asyncio
import time

from ..hardware.gpio.gpio_controller import GPIOController
from ..hardware.i2c.interface import I2CPWMInterface
from ..robot_state import RobotState
from .follow_band import compute_follow_pwm, stop_pwm

DEFAULT_MOTOR_PAIRS = {"FL": (0, 1), "FR": (3, 2), "RL": (4, 5), "RR": (7, 6)}

# jesli nie dostaniemy swiezej detekcji przez ten czas, zatrzymujemy sie -
# bezpieczniej niz jechac na "slepo" w ostatnim znanym kierunku
FOLLOW_STALE_TIMEOUT_S = 0.5
FOLLOW_LOOP_INTERVAL_S = 0.1


class RobotLogic:
    def __init__(
        self,
        gpio: GPIOController,
        i2c_pwm: I2CPWMInterface,
        state: RobotState,
        motor_pairs: dict | None = None,
    ):
        self.gpio: GPIOController = gpio
        self.i2c_pwm: I2CPWMInterface = i2c_pwm
        self.state: RobotState = state
        self.motor_pairs: dict = motor_pairs or DEFAULT_MOTOR_PAIRS
        self._was_following: bool = False

    def setup(self):
        # self.gpio.set_named_pin("R_EN", True)
        # self.gpio.set_named_pin("L_EN", True)
        pass

    def _apply_pwm(self, channel_values: dict) -> None:
        for channel, pwm in channel_values.items():
            self.i2c_pwm.set_pwm(channel, 0, pwm)

    def _tick_follow_band(self) -> None:
        color_state = self.state.color_detection_state

        is_fresh = color_state is not None and (time.time() - color_state.last_update) < FOLLOW_STALE_TIMEOUT_S
        can_follow = is_fresh and color_state.green_on_yellow_detected and color_state.target_bbox is not None

        if can_follow:
            frame = self.state.last_frame
            frame_width = frame.width if frame is not None else 0
            channel_values = compute_follow_pwm(
                color_state.target_bbox, frame_width, self.state.follow_band_max_pwm, self.motor_pairs
            )
            self._apply_pwm(channel_values)
            self._was_following = True
        elif self._was_following:
            self._apply_pwm(stop_pwm(self.motor_pairs))
            self._was_following = False

    async def run(self):
        self.setup()
        while True:
            if self.state.follow_band_mode:
                self._tick_follow_band()
            elif self._was_following:
                self._apply_pwm(stop_pwm(self.motor_pairs))
                self._was_following = False

            await asyncio.sleep(FOLLOW_LOOP_INTERVAL_S)