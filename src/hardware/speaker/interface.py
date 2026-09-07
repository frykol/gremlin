from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PlaybackState:
    is_playing: bool
    current_file: str | None
    position: float  # seconds


class SpeakerInterface(ABC):
    @abstractmethod
    def play(self, file_path: str, volume: float = 1.0) -> bool:
        """Play audio file. Returns True if started successfully."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop current playback."""
        pass

    @abstractmethod
    def get_state(self) -> PlaybackState:
        """Get current playback state."""
        pass
