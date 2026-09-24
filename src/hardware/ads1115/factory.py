import asyncio

from .interface import ADS1115Interface
from .dummy_ads1115 import FakeADS1115
from ..status_log import log_device_status
from ..device_slot import DeviceSlot
from ..device_monitor import DeviceMonitor, start_device_monitor

DEVICE_NAME = "ADS1115"


def _build_dummy(config: dict) -> ADS1115Interface:
    # DeviceMonitor podmienia instancje w slocie w trakcie dzialania robota -
    # zaden worker nie wywola juz .start() na tej nowej instancji (robi to
    # tylko raz, przy starcie calego robota), wiec musimy ja wystartowac
    # tutaj, inaczej dane przestalyby plynac na dobre po pierwszym fallbacku.
    ads = FakeADS1115()
    ads.start()
    return ads


def _build_real(config: dict) -> ADS1115Interface:
    from .ads1115 import ADS1115

    ads_config = config.get("ads1115", {})

    ads = ADS1115(
        bus=ads_config.get("bus", 2),
        address=ads_config.get("address", 0x48),
        gain=ads_config.get("gain", 1),
        data_rate=ads_config.get("data_rate", 128),
    )
    # Magistrala I2C otwiera sie dopiero w start(), nie w __init__ - bez tego
    # wywolania brak/awaria czujnika nigdy nie trafialaby do try.
    ads.start()
    return ads


def create_ads1115(config: dict) -> DeviceSlot:
    ads_config = config.get("ads1115", {})
    is_dummy = ads_config.get("is_dummy", False)
    poll_interval = config.get("device_health_check_interval", 5.0)

    if is_dummy:
        log_device_status(DEVICE_NAME, "SUCCESS - DUMMY")
        return DeviceSlot(_build_dummy(config))

    try:
        instance: ADS1115Interface = _build_real(config)
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
