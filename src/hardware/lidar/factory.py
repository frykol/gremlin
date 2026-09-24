import asyncio

from .interface import LidarInterface
from .dummy_lidar import DummyLidar
from ..status_log import log_device_status
from ..device_slot import DeviceSlot
from ..device_monitor import DeviceMonitor, start_device_monitor

DEVICE_NAME = "LIDAR"


def _build_dummy(config: dict) -> LidarInterface:
    # DeviceMonitor podmienia instancje w slocie w trakcie dzialania robota -
    # zaden worker nie wywola juz .start() na tej nowej instancji (robi to
    # tylko raz, przy starcie calego robota), wiec musimy ja wystartowac
    # tutaj, inaczej dane przestalyby plynac na dobre po pierwszym fallbacku.
    lidar = DummyLidar()
    lidar.start()
    return lidar


def _build_real(config: dict) -> LidarInterface:
    from .unitree_l1 import UnitreeL1Lidar

    lidar_config = config.get("lidar", {})

    lidar = UnitreeL1Lidar(
        port=lidar_config.get("port", "/dev/ttyUSB0"),
        baud=lidar_config.get("baud", 2_000_000),
        range_min=lidar_config.get("range_min", 0.05),
        range_max=lidar_config.get("range_max", 30.0),
        intensity_max=lidar_config.get("intensity_max", 255),
    )
    # Port szeregowy otwiera sie dopiero w start(), nie w __init__ - bez tego
    # wywolania brak/awaria lidaru nigdy nie trafialaby do try.
    lidar.start()
    return lidar


def create_lidar(config: dict) -> DeviceSlot:
    lidar_config = config.get("lidar", {})

    is_dummy = lidar_config.get("is_dummy", False)
    external_bridge = lidar_config.get("external_bridge", False)
    poll_interval = config.get("device_health_check_interval", 5.0)

    if is_dummy or external_bridge:
        log_device_status(DEVICE_NAME, "SUCCESS - DUMMY")
        slot = DeviceSlot(_build_dummy(config))
        slot.monitor = DeviceMonitor(
            name=DEVICE_NAME,
            slot=slot,
            build_real=lambda: _build_real(config),
            build_dummy=lambda: _build_dummy(config),
            poll_interval=poll_interval,
            desired_powered=False,
        )
        slot.monitor_task = start_device_monitor(slot.monitor)
        return slot

    try:
        instance: LidarInterface = _build_real(config)
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
    slot.monitor = monitor
    slot.monitor_task = start_device_monitor(monitor)

    return slot
