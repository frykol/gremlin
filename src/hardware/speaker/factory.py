from .interface import SpeakerInterface
from .dummy_speaker import DummySpeaker
from ..status_log import log_device_status

DEVICE_NAME = "SPEAKER"


def create_speaker(config: dict) -> SpeakerInterface:
    speaker_config = config.get("speaker", {})

    is_dummy = speaker_config.get("is_dummy", False)

    if is_dummy:
        log_device_status(DEVICE_NAME, "SUCCESS - DUMMY")
        return DummySpeaker()

    from .i2s_speaker import I2SSpeaker

    alsa_device = speaker_config.get("alsa_device", "plughw:CARD=sndrpihifiberry,DEV=0")

    try:
        speaker = I2SSpeaker(alsa_device=alsa_device)
    except Exception as e:
        log_device_status(DEVICE_NAME, "ERROR")
        print(f"Failed to initialize {DEVICE_NAME}: {e}")
        log_device_status(DEVICE_NAME, "ERROR - FALLBACK TO DUMMY")
        return DummySpeaker()

    log_device_status(DEVICE_NAME, "SUCCESS")
    return speaker
