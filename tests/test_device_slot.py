from src.hardware.device_slot import DeviceSlot, resolve


def test_slot_get_returns_initial_value():
    slot = DeviceSlot("real")
    assert slot.get() == "real"


def test_slot_set_replaces_value():
    slot = DeviceSlot("real")
    slot.set("dummy")
    assert slot.get() == "dummy"


def test_resolve_unwraps_slot():
    slot = DeviceSlot("real")
    assert resolve(slot) == "real"

    slot.set("dummy")
    assert resolve(slot) == "dummy"


def test_resolve_passes_through_non_slot_values():
    class FakeDevice:
        pass

    device = FakeDevice()
    assert resolve(device) is device
    assert resolve(None) is None
