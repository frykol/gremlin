import random
from typing import List, Tuple

from .interface import LidarInterface


class DummyLidar(LidarInterface):
    def __init__(self, **kwargs):
        self.running = False

    def start(self) -> None:
        self.running = True
        print("Lidar (dummy) działa")

    def stop(self) -> None:
        self.running = False
        print("Lidar (dummy) zatrzymany")

    def read_points(self) -> List[Tuple[float, float, float]]:
        if not self.running:
            return []

        return [
            (
                round(random.uniform(-5.0, 5.0), 3),
                round(random.uniform(0.0, 10.0), 3),
                round(random.uniform(-1.0, 1.0), 3),
            )
            for _ in range(20)
        ]
