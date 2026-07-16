import random
from typing import List

from .interface import ADS1115Interface


class FakeADS1115(ADS1115Interface):
    def __init__(self, **kwargs):
        self.running = False

    def start(self) -> None:
        self.running = True
        print("ADS1115 (dummy) działa")

    def stop(self) -> None:
        self.running = False
        print("ADS1115 (dummy) zatrzymany")

    def read_channels(self) -> List[float]:
        if not self.running:
            return [0.0, 0.0, 0.0, 0.0]

        return [round(random.uniform(0.0, 16.8), 3) for _ in range(4)]
