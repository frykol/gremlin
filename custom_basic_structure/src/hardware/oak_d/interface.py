from abc import ABC, abstractmethod
from dataclasses import dataclass
import numpy as np
from typing import Optional

@dataclass
class CameraFrame:
    image: np.ndarray
    timestamp: float
    width: int
    height: int
    frame_id: int

class CameraInterface(ABC):
    @abstractmethod
    def start(self) -> None:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass

    @abstractmethod
    def get_camera_frame(self) -> Optional[CameraFrame]:
        pass
