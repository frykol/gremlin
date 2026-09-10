from src.hardware.gamepad.dummy_gamepad import FakeGamepad


def test_dummy_gamepad_starts_and_returns_neutral_state_from_mapping():
    mapping = {"BTN_SOUTH": "a", "ABS_X": "left_stick_x"}
    gamepad = FakeGamepad(mapping=mapping)

    gamepad.start()

    assert gamepad.running is True
    state = gamepad.get_state()
    assert state.buttons == {"a": False}
    assert state.axes == {"left_stick_x": 0.0}
    assert gamepad.is_healthy() is True

    gamepad.stop()
    assert gamepad.running is False
