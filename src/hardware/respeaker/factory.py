import asyncio

from .interface import MicArrayInterface
from .dummy_respeaker import FakeReSpeakerMicArray
from ..status_log import log_device_status
from ..device_slot import DeviceSlot
from ..device_monitor import DeviceMonitor, start_device_monitor

DEVICE_NAME = "MIC"


def _build_dummy(config: dict) -> MicArrayInterface:
    respeaker_config = config.get("respeaker", {})
    mic = FakeReSpeakerMicArray(
        sample_rate=respeaker_config.get("sample_rate", 16000),
        channels=respeaker_config.get("channels", 6),
        chunk_size=respeaker_config.get("chunk_size", 1024),
    )
    # DeviceMonitor podmienia instancje w slocie w trakcie dzialania robota -
    # zaden worker nie wywola juz .start() na tej nowej instancji (robi to
    # tylko raz, przy starcie calego robota), wiec musimy ja wystartowac
    # tutaj, inaczej dane przestalyby plynac na dobre po pierwszym fallbacku.
    mic.start()
    return mic


def _build_real(config: dict) -> MicArrayInterface:
    from .respeaker import ReSpeakerMicArray

    respeaker_config = config.get("respeaker", {})

    mic = ReSpeakerMicArray(
        sample_rate=respeaker_config.get("sample_rate", 16000),
        channels=respeaker_config.get("channels", 6),
        chunk_size=respeaker_config.get("chunk_size", 1024),
        device_name=respeaker_config.get("device_name", "ReSpeaker 4 Mic Array"),
    )
    # Strumien audio otwiera sie dopiero w start(), nie w __init__ - bez tego
    # wywolania brak/awaria mikrofonu nigdy nie trafialaby do try.
    mic.start()
    return mic


def create_mic_array(config: dict) -> DeviceSlot:
    respeaker_config = config.get("respeaker", {})
    is_dummy = respeaker_config.get("is_dummy", False)
    poll_interval = config.get("device_health_check_interval", 5.0)

    if is_dummy:
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
        instance: MicArrayInterface = _build_real(config)
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
