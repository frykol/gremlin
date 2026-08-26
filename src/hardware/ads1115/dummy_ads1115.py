import random
from typing import List, Tuple

from .interface import ADS1115Interface

# Powiela stosunek PRZELICZNIK z ads1115.py, żeby symulowane surowe
# napięcie ADC było spójne z przeliczonym napięciem.
DUMMY_PRZELICZNIK = 16.8 / 3.185


class FakeADS1115(ADS1115Interface):
    def __init__(self, **kwargs):
        self.running = False

    def start(self) -> None:
        self.running = True
        print("ADS1115 (dummy) działa")

    def stop(self) -> None:
        self.running = False
        print("ADS1115 (dummy) zatrzymany")

    def read_channels(self) -> List[Tuple[float, float]]:
        if not self.running:
            return [(0.0, 0.0)] * 4

        result = []
        for _ in range(4):
            voltage = round(random.uniform(0.0, 16.8), 3)
            raw_voltage = voltage / DUMMY_PRZELICZNIK
            result.append((raw_voltage, voltage))

        return result
