import json

import numpy as np
import pytest

from wheel_kinematics import WHEEL_CHANNELS
from wheel_odometry_reader import WheelOdometryReader


def write_state(path, t_mono, channels):
    path.write_text(json.dumps({"t_mono": t_mono, "channels": channels}))


def test_poll_delta_none_on_first_call(tmp_path):
    path = tmp_path / "wheel_state.json"
    write_state(path, t_mono=100.0, channels={})
    reader = WheelOdometryReader(str(path), max_wheel_speed_rad_s=10.0)

    assert reader.poll_delta(max_age_s=1e9) is None


def test_poll_delta_none_when_file_missing(tmp_path):
    path = tmp_path / "does_not_exist.json"
    reader = WheelOdometryReader(str(path), max_wheel_speed_rad_s=10.0)

    assert reader.poll_delta() is None


def test_poll_delta_none_when_stale(tmp_path):
    path = tmp_path / "wheel_state.json"
    write_state(path, t_mono=1.0, channels={})
    reader = WheelOdometryReader(str(path), max_wheel_speed_rad_s=10.0)

    assert reader.poll_delta(max_age_s=0.5) is None


def test_poll_delta_pure_forward_motion(tmp_path):
    path = tmp_path / "wheel_state.json"
    reader = WheelOdometryReader(str(path), max_wheel_speed_rad_s=10.0)

    all_forward_full = {}
    for fwd_ch, bwd_ch in WHEEL_CHANNELS.values():
        all_forward_full[str(fwd_ch)] = 4095
        all_forward_full[str(bwd_ch)] = 0

    write_state(path, t_mono=100.0, channels=all_forward_full)
    assert reader.poll_delta(max_age_s=1e9) is None  # pierwszy odczyt: brak dt do scalkowania

    write_state(path, t_mono=101.0, channels=all_forward_full)
    result = reader.poll_delta(max_age_s=1e9)

    assert result is not None
    dR, dt = result
    # domyslne r=0.024, pelna predkosc 10 rad/s na wszystkich kolach przez
    # 1s ruchu czysto do przodu -> dx = r * max_wheel_speed_rad_s * 1.0
    expected_dx = 0.024 * 10.0 * 1.0
    assert dt[0] == pytest.approx(expected_dx, rel=1e-6)
    assert dt[1] == pytest.approx(0.0, abs=1e-9)
    np.testing.assert_allclose(dR, np.eye(3), atol=1e-9)
