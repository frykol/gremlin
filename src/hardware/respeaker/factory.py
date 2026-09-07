from .interface import MicArrayInterface
from .dummy_respeaker import FakeReSpeakerMicArray
from ..status_log import log_device_status

DEVICE_NAME = "MIC"


def create_mic_array(config: dict) -> MicArrayInterface:
    respeaker_config = config.get("respeaker", {})

    sample_rate = respeaker_config.get("sample_rate", 16000)
    channels = respeaker_config.get("channels", 6)
    chunk_size = respeaker_config.get("chunk_size", 1024)
    device_name = respeaker_config.get("device_name", "ReSpeaker 4 Mic Array")
    is_dummy = respeaker_config.get("is_dummy", False)

    if not is_dummy:
        from .respeaker import ReSpeakerMicArray

        try:
            mic = ReSpeakerMicArray(
                sample_rate=sample_rate,
                channels=channels,
                chunk_size=chunk_size,
                device_name=device_name,
            )
            # Strumien audio otwiera sie dopiero w start(), nie w __init__ -
            # bez tego wywolania brak/awaria mikrofonu nigdy nie trafialaby do try.
            mic.start()
        except Exception as e:
            log_device_status(DEVICE_NAME, "ERROR")
            print(f"Failed to initialize {DEVICE_NAME}: {e}")
            log_device_status(DEVICE_NAME, "ERROR - FALLBACK TO DUMMY")
            return FakeReSpeakerMicArray(
                sample_rate=sample_rate,
                channels=channels,
                chunk_size=chunk_size,
            )

        log_device_status(DEVICE_NAME, "SUCCESS")
        return mic

    log_device_status(DEVICE_NAME, "SUCCESS - DUMMY")
    return FakeReSpeakerMicArray(
        sample_rate=sample_rate,
        channels=channels,
        chunk_size=chunk_size,
    )
