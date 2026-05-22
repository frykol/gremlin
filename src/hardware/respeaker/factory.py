from .interface import MicArrayInterface
from .dummy_respeaker import FakeReSpeakerMicArray

def create_mic_array(is_dev: bool, config: dict) -> MicArrayInterface:
    respeaker_config = config.get("respeaker", {})

    sample_rate = respeaker_config.get("sample_rate", 16000)
    channels = respeaker_config.get("channels", 6)
    chunk_size = respeaker_config.get("chunk_size", 1024)
    device_name = respeaker_config.get("device_name", "ReSpeaker 4 Mic Array")

    if is_dev:
        from .respeaker import ReSpeakerMicArray

        return ReSpeakerMicArray(
            sample_rate=sample_rate,
            channels=channels,
            chunk_size=chunk_size,
            device_name=device_name,
        )

    return FakeReSpeakerMicArray(
        sample_rate=sample_rate,
        channels=channels,
        chunk_size=chunk_size,
    )
