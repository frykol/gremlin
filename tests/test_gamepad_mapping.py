import pytest

from src.hardware.gamepad.mapping import (
    is_button_code,
    is_axis_code,
    neutral_state,
    normalize_axis_value,
)


def test_is_button_code_matches_btn_prefix():
    assert is_button_code("BTN_SOUTH") is True
    assert is_button_code("ABS_X") is False


def test_is_axis_code_matches_abs_prefix():
    assert is_axis_code("ABS_X") is True
    assert is_axis_code("BTN_SOUTH") is False


def test_neutral_state_splits_buttons_and_axes_by_prefix():
    mapping = {"BTN_SOUTH": "a", "ABS_X": "left_stick_x", "BTN_EAST": "b"}

    state = neutral_state(mapping)

    assert state.buttons == {"a": False, "b": False}
    assert state.axes == {"left_stick_x": 0.0}


def test_normalize_axis_value_maps_range_to_minus_one_one():
    assert normalize_axis_value(0, 0, 255) == -1.0
    assert normalize_axis_value(255, 0, 255) == 1.0
    assert normalize_axis_value(127, 0, 255) == pytest.approx(-0.00392, abs=1e-4)


def test_normalize_axis_value_clamps_out_of_range_input():
    assert normalize_axis_value(-10, 0, 255) == -1.0
    assert normalize_axis_value(300, 0, 255) == 1.0


def test_normalize_axis_value_handles_degenerate_range():
    assert normalize_axis_value(5, 5, 5) == 0.0
