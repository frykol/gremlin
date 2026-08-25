from abc import ABC, abstractmethod
from typing import List, Tuple


class LidarInterface(ABC):
    @abstractmethod
    def start(self) -> None:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass

    @abstractmethod
    def read_points(self) -> List[Tuple[float, float, float, int]]:
        """Zwraca punkty [x, y, z, intensity] zebrane od ostatniego wywolania
        (intensity - sila odbicia 0-255, moze byc pusta lista)."""
        pass
