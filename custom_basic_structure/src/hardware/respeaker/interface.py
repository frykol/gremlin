from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import numpy as np

@dataclass
class AudioChunk:
    samples: np.ndarray
    timestamp: float
    sample_rate: int
    channels: int
    chunk_id: int

class MicArrayInterface(ABC):
    @abstractmethod
    def start(self) -> None:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass

    @abstractmethod
    def get_audio_chunk(self) -> Optional[AudioChunk]:
        pass
