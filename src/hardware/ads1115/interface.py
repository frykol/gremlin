from abc import ABC, abstractmethod
from typing import List, Tuple

class ADS1115Interface(ABC):
    @abstractmethod
    def start(self) -> None:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass

    @abstractmethod
    def read_channels(self) -> List[Tuple[float, float]]:
        """Zwraca (surowe napięcie na ADC, przeliczone napięcie po PRZELICZNIK) dla kanałów AIN0-AIN3."""
        pass
