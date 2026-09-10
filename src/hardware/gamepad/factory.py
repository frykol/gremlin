from .interface import GamepadInterface
from .dummy_gamepad import FakeGamepad
from ..status_log import log_device_status
from ..device_slot import DeviceSlot
from ..device_monitor import DeviceMonitor, start_device_monitor

DEVICE_NAME = "GAMEPAD"


def _build_dummy(config: dict) -> GamepadInterface:
    gamepad_config = config.get("gamepad", {})
    gamepad = FakeGamepad(mapping=gamepad_config.get("mapping", {}))
    # DeviceMonitor podmienia instancje w slocie w trakcie dzialania robota -
    # zaden worker nie wywola juz .start() na tej nowej instancji, wiec
    # musimy ja wystartowac tutaj (patrz respeaker/factory.py po ten sam
    # wzorzec i uzasadnienie).
    gamepad.start()
    return gamepad


def _build_real(config: dict) -> GamepadInterface:
    from .gamepad import Gamepad

    gamepad_config = config.get("gamepad", {})
    gamepad = Gamepad(mapping=gamepad_config.get("mapping", {}))
    gamepad.start()
    return gamepad


def create_gamepad(config: dict) -> DeviceSlot:
    gamepad_config = config.get("gamepad", {})
    is_dummy = gamepad_config.get("is_dummy", False)
    poll_interval = config.get("device_health_check_interval", 5.0)

    if is_dummy:
        log_device_status(DEVICE_NAME, "SUCCESS - DUMMY")
        slot = DeviceSlot(_build_dummy(config))
        slot.monitor_task = None
        return slot

    try:
        instance: GamepadInterface = _build_real(config)
        log_device_status(DEVICE_NAME, "SUCCESS")
    except Exception as e:
        log_device_status(DEVICE_NAME, "ERROR")
        print(f"Failed to initialize {DEVICE_NAME}: {e}")
        log_device_status(DEVICE_NAME, "ERROR - FALLBACK TO DUMMY")
        instance = _build_dummy(config)

    slot = DeviceSlot(instance)

    monitor = DeviceMonitor(
        name=DEVICE_NAME,
        slot=slot,
        build_real=lambda: _build_real(config),
        build_dummy=lambda: _build_dummy(config),
        poll_interval=poll_interval,
    )
    slot.monitor_task = start_device_monitor(monitor)

    return slot
