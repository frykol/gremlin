import time
from .interface import SpeakerInterface, PlaybackState


class DummySpeaker(SpeakerInterface):
    def __init__(self):
        self.current_file: str | None = None
        self.is_playing: bool = False
        self.start_time: float = 0.0
        self.duration: float = 0.0

    def play(self, file_path: str, volume: float = 1.0) -> bool:
        print(f"[DummySpeaker] Playing: {file_path} (volume={volume})")
        self.current_file = file_path
        self.is_playing = True
        self.start_time = time.time()
        self.duration = 2.0  # Mock 2-second playback
        return True

    def stop(self) -> None:
        if self.is_playing:
            print(f"[DummySpeaker] Stopped: {self.current_file}")
        self.is_playing = False
        self.current_file = None

    def get_state(self) -> PlaybackState:
        if self.is_playing and time.time() - self.start_time >= self.duration:
            self.is_playing = False
            self.current_file = None

        position = time.time() - self.start_time if self.is_playing else 0.0
        return PlaybackState(
            is_playing=self.is_playing,
            current_file=self.current_file,
            position=position,
        )
