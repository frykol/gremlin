"""
Odczyt stanu kol (zapisywanego przez CommandProcessor.write_wheel_state()
w gremlin/src) i przeliczenie go na przyrostowa transformacje SE(2) (dR
wokol osi Z, dt w plaszczyznie XY) do wykorzystania jako initial guess dla
ICP w lidar_slam.py.
"""
import json
import math
import os
import sys
import time

import numpy as np

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "ros2_ws", "src", "motor_driver"),
)
from motor_driver.odometry import integrate_odometry  # noqa: E402

from wheel_kinematics import (  # noqa: E402
    WHEEL_CHANNELS,
    pwm_pair_to_signed_fraction,
    wheel_speeds_to_body_velocity,
)


class WheelOdometryReader:
    def __init__(self, state_path: str, max_wheel_speed_rad_s: float):
        self.state_path = state_path
        self.max_wheel_speed_rad_s = max_wheel_speed_rad_s
        self._last_t_mono = None
        self._x = 0.0
        self._y = 0.0
        self._theta = 0.0

    def _read_state(self):
        try:
            with open(self.state_path) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def poll_delta(self, max_age_s: float = 1.0):
        """Zwraca (dR, dt) - przyrostowa transformacje SE(2) od ostatniego
        wywolania, albo None gdy brak swiezych danych o predkosciach kol
        (plik nieobecny/nieaktualny) lub to pierwsze wywolanie (nie ma
        jeszcze poprzedniego znacznika czasu do policzenia dt)."""
        data = self._read_state()
        if data is None:
            self._last_t_mono = None
            return None

        t_mono = data["t_mono"]
        if time.monotonic() - t_mono > max_age_s:
            self._last_t_mono = None
            return None

        if self._last_t_mono is None:
            self._last_t_mono = t_mono
            return None

        dt_elapsed = t_mono - self._last_t_mono
        self._last_t_mono = t_mono
        if dt_elapsed <= 0:
            return None

        channels = {int(k): v for k, v in data["channels"].items()}
        wheel_speeds = {}
        for name, (fwd_ch, bwd_ch) in WHEEL_CHANNELS.items():
            frac = pwm_pair_to_signed_fraction(
                channels.get(fwd_ch, 0), channels.get(bwd_ch, 0)
            )
            wheel_speeds[name] = frac * self.max_wheel_speed_rad_s

        vx, vy, wz = wheel_speeds_to_body_velocity(
            wheel_speeds["FL"], wheel_speeds["FR"],
            wheel_speeds["RL"], wheel_speeds["RR"],
        )

        x0, y0, theta0 = self._x, self._y, self._theta
        self._x, self._y, self._theta = integrate_odometry(
            self._x, self._y, self._theta, vx, vy, wz, dt_elapsed
        )

        dx = self._x - x0
        dy = self._y - y0
        dtheta = self._theta - theta0

        cos_t, sin_t = math.cos(dtheta), math.sin(dtheta)
        dR = np.array([
            [cos_t, -sin_t, 0.0],
            [sin_t, cos_t, 0.0],
            [0.0, 0.0, 1.0],
        ])
        dt = np.array([dx, dy, 0.0])
        return dR, dt
