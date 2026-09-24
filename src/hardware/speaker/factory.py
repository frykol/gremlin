import asyncio

from .interface import SpeakerInterface
from .dummy_speaker import DummySpeaker
from ..status_log import log_device_status
from ..device_slot import DeviceSlot
from ..device_monitor import DeviceMonitor, start_device_monitor

DEVICE_NAME = "SPEAKER"


def _build_dummy(config: dict) -> SpeakerInterface:
    return DummySpeaker()


def _build_real(config: dict) -> SpeakerInterface:
    from .i2s_speaker import I2SSpeaker

    speaker_config = config.get("speaker", {})
    alsa_device = speaker_config.get("alsa_device", "plughw:CARD=sndrpihifiberry,DEV=0")

    speaker = I2SSpeaker(alsa_device=alsa_device)
    # I2SSpeaker nie ma metody start() (odtwarzanie idzie przez subprocesy
    # per-plik) - jedyna dostepna weryfikacja obecnosci karty ALSA to
    # is_healthy() zaraz po konstrukcji.
    if not speaker.is_healthy():
        raise RuntimeError(f"ALSA device not found: {alsa_device}")
    return speaker


def create_speaker(config: dict) -> DeviceSlot:
    speaker_config = config.get("speaker", {})
    is_dummy = speaker_config.get("is_dummy", False)
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
        instance: SpeakerInterface = _build_real(config)
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
