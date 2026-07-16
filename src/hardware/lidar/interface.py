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
    def read_points(self) -> List[Tuple[float, float, float]]:
        """Zwraca punkty [x, y, z] zebrane od ostatniego wywolania (moze byc pusta lista)."""
        pass
