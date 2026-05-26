from dataclasses import dataclass
from .hardware.oak_d.interface import CameraFrame

@dataclass
class RobotState:
    stream_enabled: bool = False
    last_frame: CameraFrame | None = None