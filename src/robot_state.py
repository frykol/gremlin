from dataclasses import dataclass, field

import numpy as np

from .hardware.oak_d.interface import CameraFrame
from .services.hand_gestures import HandGestureResult


@dataclass
class RobotState:
    stream_enabled: bool = False
    last_frame: CameraFrame | None = None
    display_frame: np.ndarray | None = None
    last_gestures: list[HandGestureResult] = field(default_factory=list)
    gesture_name: str = "brak"