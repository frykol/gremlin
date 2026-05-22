import time
from typing import Optional

import numpy as np

from .interface import MicArrayInterface, AudioChunk

class FakeReSpeakerMicArray(MicArrayInterface):
    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 6,
        chunk_size: int = 1024,
    ):
        self.sample_rate: int = sample_rate
        self.channels: int = channels
        self.chunk_size: int = chunk_size

        self.running: bool = False
        self.chunk_id: int = 0

    def start(self) -> None:
        self.running = True
        print("ReSpeaker mic array (dummy) działa")

    def stop(self) -> None:
        self.running = False
        print("ReSpeaker mic array (dummy) zatrzymana")

    def get_audio_chunk(self) -> Optional[AudioChunk]:
        if not self.running:
            return None

        self.chunk_id += 1

        t = np.arange(self.chunk_size) / self.sample_rate
        phase = self.chunk_id * 0.1
        tone = (np.sin(2 * np.pi * 440 * t + phase) * 8000).astype(np.int16)

        samples = np.zeros((self.chunk_size, self.channels), dtype=np.int16)
        samples[:, 0] = tone

        return AudioChunk(
            samples=samples,
            timestamp=time.time(),
            sample_rate=self.sample_rate,
            channels=self.channels,
            chunk_id=self.chunk_id,
        )
