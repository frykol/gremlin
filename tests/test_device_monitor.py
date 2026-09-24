import asyncio

from src.hardware.device_slot import DeviceSlot
from src.hardware.device_monitor import DeviceMonitor, start_device_monitor


class FakeReal:
    IS_DUMMY = False

    def __init__(self, healthy=True):
        self._healthy = healthy
        self.stopped = False

    def is_healthy(self) -> bool:
        return self._healthy

    def stop(self) -> None:
        self.stopped = True


class FakeDummy:
    IS_DUMMY = True

    def is_healthy(self) -> bool:
        return True


async def _run_until(monitor: DeviceMonitor, predicate, timeout=2.0):
    monitor.poll_interval = 0
    task = asyncio.create_task(monitor.run())
    try:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if predicate():
                return
            await asyncio.sleep(0.01)
        raise AssertionError("predicate never became true")
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def _run_for(monitor: DeviceMonitor, duration=0.1):
    """Odpala monitor przez chwile - do testowania, ze stan sie NIE zmienia
    (nie ma tu warunku na ktory mozna by czekac przez _run_until)."""
    monitor.poll_interval = 0
    task = asyncio.create_task(monitor.run())
    await asyncio.sleep(duration)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def test_monitor_falls_back_to_dummy_when_real_device_unhealthy():
    async def scenario():
        real = FakeReal(healthy=False)
        dummy = FakeDummy()
        slot = DeviceSlot(real)

        def still_disconnected():
            raise RuntimeError("still disconnected")

        monitor = DeviceMonitor(
            name="TEST",
            slot=slot,
            build_real=still_disconnected,
            build_dummy=lambda: dummy,
            poll_interval=0,
        )

        await _run_until(monitor, lambda: slot.get() is dummy)

        assert real.stopped is True

    asyncio.run(scenario())


def test_monitor_leaves_healthy_real_device_in_place():
    async def scenario():
        real = FakeReal(healthy=True)
        slot = DeviceSlot(real)

        monitor = DeviceMonitor(
            name="TEST",
            slot=slot,
            build_real=lambda: FakeReal(),
            build_dummy=lambda: FakeDummy(),
            poll_interval=0,
        )

        await _run_for(monitor)

        assert slot.get() is real

    asyncio.run(scenario())


def test_monitor_reconnects_to_real_device_when_dummy_active():
    async def scenario():
        dummy = FakeDummy()
        slot = DeviceSlot(dummy)
        rebuilt = FakeReal(healthy=True)

        monitor = DeviceMonitor(
            name="TEST",
            slot=slot,
            build_real=lambda: rebuilt,
            build_dummy=lambda: FakeDummy(),
            poll_interval=0,
        )

        await _run_until(monitor, lambda: slot.get() is rebuilt)

    asyncio.run(scenario())


def test_monitor_stays_dummy_when_reconnect_attempt_fails():
    async def scenario():
        dummy = FakeDummy()
        slot = DeviceSlot(dummy)

        def failing_build_real():
            raise RuntimeError("still disconnected")

        monitor = DeviceMonitor(
            name="TEST",
            slot=slot,
            build_real=failing_build_real,
            build_dummy=lambda: FakeDummy(),
            poll_interval=0,
        )

        await _run_for(monitor)

        assert slot.get() is dummy

    asyncio.run(scenario())


def test_power_off_replaces_real_with_dummy_and_blocks_reconnect():
    async def scenario():
        real = FakeReal(healthy=True)
        dummy = FakeDummy()
        rebuilt = FakeReal(healthy=True)
        slot = DeviceSlot(real)
        monitor = DeviceMonitor(
            name="TEST",
            slot=slot,
            build_real=lambda: rebuilt,
            build_dummy=lambda: dummy,
            poll_interval=0,
        )

        await monitor.set_powered(False)
        assert slot.get() is dummy
        assert real.stopped is True

        await _run_for(monitor)
        assert slot.get() is dummy

    asyncio.run(scenario())


def test_power_on_replaces_dummy_with_real():
    async def scenario():
        dummy = FakeDummy()
        rebuilt = FakeReal(healthy=True)
        slot = DeviceSlot(dummy)
        monitor = DeviceMonitor(
            name="TEST",
            slot=slot,
            build_real=lambda: rebuilt,
            build_dummy=lambda: FakeDummy(),
            poll_interval=0,
        )

        await monitor.set_powered(True)

        assert slot.get() is rebuilt

    asyncio.run(scenario())


def test_start_device_monitor_returns_none_without_running_loop():
    slot = DeviceSlot(FakeDummy())
    monitor = DeviceMonitor(
        name="TEST",
        slot=slot,
        build_real=lambda: FakeReal(),
        build_dummy=lambda: FakeDummy(),
        poll_interval=5.0,
    )

    assert start_device_monitor(monitor) is None
