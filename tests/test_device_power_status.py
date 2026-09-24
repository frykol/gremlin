import asyncio

from src.hardware.device_power_controller import DevicePowerController
from src.services.command_processor import CommandProcessor


class FakeMonitor:
    def __init__(self):
        self.calls = []

    async def set_powered(self, powered):
        self.calls.append(powered)


class FakeGpio:
    pins = set()
    standard_pins = set()


def test_device_power_status_maps_protocol_names_to_monitors():
    monitors = {name: FakeMonitor() for name in ("camera", "lidar", "mic", "speaker")}
    controller = DevicePowerController(
        camera=monitors["camera"],
        lidar=monitors["lidar"],
        mic=monitors["mic"],
        speaker=monitors["speaker"],
    )

    asyncio.run(controller.apply({
        "OAK-D": True,
        "LIDAR": False,
        "MIC": False,
        "SPEAKER": True,
    }))

    assert monitors["camera"].calls == [True]
    assert monitors["lidar"].calls == [False]
    assert monitors["mic"].calls == [False]
    assert monitors["speaker"].calls == [True]


def test_device_power_status_ignores_unknown_and_non_boolean_values():
    monitor = FakeMonitor()
    controller = DevicePowerController(
        camera=monitor,
        lidar=FakeMonitor(),
        mic=FakeMonitor(),
        speaker=FakeMonitor(),
    )

    asyncio.run(controller.apply({"UNKNOWN": True, "OAK-D": 1, "MIC": "false"}))

    assert monitor.calls == []


def test_command_processor_dispatches_device_power_status():
    monitor = FakeMonitor()
    controller = DevicePowerController(
        camera=monitor,
        lidar=FakeMonitor(),
        mic=FakeMonitor(),
        speaker=FakeMonitor(),
    )
    processor = CommandProcessor(
        command_queue=asyncio.Queue(),
        gpio=FakeGpio(),
        device_power_controller=controller,
    )

    asyncio.run(processor._dispatch_command({
        "type": "device_power_status",
        "devices": {"OAK-D": False},
    }))

    assert monitor.calls == [False]
