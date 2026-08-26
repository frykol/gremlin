from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np


@dataclass
class AnklePositions:
    left: Optional[Tuple[int, int]]
    right: Optional[Tuple[int, int]]


class PoseEstimatorInterface(ABC):
    @abstractmethod
    def get_ankle_positions(self, image: np.ndarray) -> AnklePositions:
        pass
