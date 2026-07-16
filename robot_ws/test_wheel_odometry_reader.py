import asyncio
import json
import os
import sys

import numpy as np
import pytest

from wheel_kinematics import WHEEL_CHANNELS
from wheel_odometry_reader import WheelOdometryReader

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.services.command_processor import CommandProcessor  # noqa: E402
from src.robot_state import RobotState  # noqa: E402


class DummyUdpFrameSender:
    def set_target(self, host, port):
        pass


class DummyGpio:
    pins = {}
    standard_pins = {}


class DummyI2cPwm:
    def set_pwm(self, channel, on, off):
        pass


class DummyWs:
    async def send(self, message):
        pass


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


def test_real_command_processor_write_wheel_state_feeds_real_reader_forward_motion(tmp_path, monkeypatch):
    """Integration test tying together Task 2 (CommandProcessor.write_wheel_state),
    Task 3 (WheelOdometryReader.poll_delta) and the wheel_kinematics used by both:
    a state file written by the REAL CommandProcessor must be readable by the
    REAL WheelOdometryReader and yield a forward-motion delta, without either
    side hand-rolling its own state-file format."""
    processor = CommandProcessor(
        command_queue=asyncio.Queue(),
        gpio=DummyGpio(),
        i2c_pwm=DummyI2cPwm(),
        state=RobotState(),
        ws=DummyWs(),
        udp_frame_sender=DummyUdpFrameSender(),
    )

    # Wszystkie kola do przodu pelnym PWM: kazdy kanal "forward" = 4095,
    # kazdy kanal "backward" = 0 (patrz WHEEL_CHANNELS).
    wheel_channel_state = {}
    for fwd_ch, bwd_ch in WHEEL_CHANNELS.values():
        wheel_channel_state[fwd_ch] = 4095
        wheel_channel_state[bwd_ch] = 0
    processor.wheel_channel_state = wheel_channel_state

    state_path = tmp_path / "wheel_state.json"

    fake_time = {"t": 100.0}
    monkeypatch.setattr("src.services.command_processor.time.monotonic", lambda: fake_time["t"])

    processor.write_wheel_state(str(state_path))

    reader = WheelOdometryReader(str(state_path), max_wheel_speed_rad_s=10.0)
    assert reader.poll_delta(max_age_s=1e9) is None  # pierwszy odczyt: brak dt do scalkowania

    fake_time["t"] = 101.0
    processor.write_wheel_state(str(state_path))

    result = reader.poll_delta(max_age_s=1e9)
    assert result is not None
    dR, dt = result

    expected_dx = 0.024 * 10.0 * 1.0  # r * max_wheel_speed_rad_s * dt_elapsed
    assert dt[0] == pytest.approx(expected_dx, rel=1e-6)
    assert dt[1] == pytest.approx(0.0, abs=1e-9)
    np.testing.assert_allclose(dR, np.eye(3), atol=1e-9)
