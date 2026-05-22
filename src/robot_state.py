from dataclasses import dataclass
from .hardware.oak_d.interface import CameraFrame
from .hardware.respeaker.interface import AudioChunk

@dataclass
class RobotState:
    stream_enabled: bool = False
    audio_stream_enabled: bool = False
    last_frame: CameraFrame | None = None
    last_audio_chunk: AudioChunk | None = None