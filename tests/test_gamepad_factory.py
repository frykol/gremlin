from src.hardware.gamepad.dummy_gamepad import FakeGamepad
from src.hardware.gamepad.factory import _build_dummy, create_gamepad
from src.hardware.device_slot import DeviceSlot


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


def test_build_dummy_gamepad_is_already_started():
    gamepad = _build_dummy({"gamepad": {"mapping": {"BTN_SOUTH": "a"}}})

    assert gamepad.running is True
    assert gamepad.get_state().buttons == {"a": False}


def test_create_gamepad_with_is_dummy_flag_returns_dummy_slot_without_monitor():
    slot = create_gamepad({"gamepad": {"is_dummy": True, "mapping": {}}})

    assert isinstance(slot, DeviceSlot)
    assert slot.get().IS_DUMMY is True
    assert slot.monitor_task is None


def test_create_gamepad_falls_back_to_dummy_when_no_real_device_available():
    # Brak sekcji "gamepad"/is_dummy=False -> probuje _build_real, ktora na
    # maszynie bez podlaczonego evdev-gamepada rzuci (RuntimeError z braku
    # urzadzenia albo ImportError jesli evdev nie jest zainstalowane) -
    # create_gamepad musi to zlapac i wystawic dzialajacego dummy zamiast
    # crashowac caly proces.
    slot = create_gamepad({"gamepad": {"is_dummy": False, "mapping": {}}})

    assert isinstance(slot, DeviceSlot)
    assert slot.get().IS_DUMMY is True
