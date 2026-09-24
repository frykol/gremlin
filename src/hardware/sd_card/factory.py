import asyncio

from .interface import SdCardInterface
from .sd_card import SdCardReader
from .dummy_sd_card import DummySdCardReader
from ..status_log import log_device_status
from ..device_slot import DeviceSlot
from ..device_monitor import DeviceMonitor, start_device_monitor

DEVICE_NAME = "SD-CARD"


def _build_dummy(config: dict) -> SdCardInterface:
    sd_card_config = config.get("sd_card", {})
    sd_card = DummySdCardReader(
        device=sd_card_config.get("device", "/dev/mmcblk1p1"),
        mount_point=sd_card_config.get("mount_point", "/mnt/sdcard"),
    )
    # DeviceMonitor podmienia instancje w slocie w trakcie dzialania robota -
    # zaden worker nie wywola juz .start() na tej nowej instancji (robi to
    # tylko raz, przy starcie calego robota), wiec musimy ja wystartowac
    # tutaj, inaczej dane przestalyby plynac na dobre po pierwszym fallbacku.
    sd_card.start()
    return sd_card


def _build_real(config: dict) -> SdCardInterface:
    sd_card_config = config.get("sd_card", {})

    sd_card = SdCardReader(
        device=sd_card_config.get("device", "/dev/mmcblk1p1"),
        mount_point=sd_card_config.get("mount_point", "/mnt/sdcard"),
    )
    # Montowanie karty odbywa sie dopiero w start(), nie w __init__ - bez
    # tego wywolania brak/awaria karty nigdy nie trafialaby do try.
    sd_card.start()
    return sd_card


def create_sd_card(config: dict) -> DeviceSlot:
    sd_card_config = config.get("sd_card", {})
    is_dummy = sd_card_config.get("is_dummy", False)
    poll_interval = config.get("device_health_check_interval", 5.0)

    if is_dummy:
        log_device_status(DEVICE_NAME, "SUCCESS - DUMMY")
        return DeviceSlot(_build_dummy(config))

    try:
        instance: SdCardInterface = _build_real(config)
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
