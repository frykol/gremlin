from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple

from .hardware.oak_d.interface import CameraFrame
from .hardware.respeaker.interface import AudioChunk

@dataclass
class ADS1115State:
    a0: float
    a1: float
    a2: float
    a3: float
    raw_a0: float = 0.0
    raw_a1: float = 0.0
    raw_a2: float = 0.0
    raw_a3: float = 0.0


@dataclass
class EncoderState:
    ticks: dict = None

    def __post_init__(self):
        if self.ticks is None:
            self.ticks = {}


class LidarBufferOverwriteMode(str, Enum):
    RING = "ring"    # po zapelnieniu nadpisuje najstarsze punkty
    RESET = "reset"  # po zapelnieniu czysci caly bufor i zaczyna zapelniac od nowa


LIDAR_POINT_SIZE_BYTES = 16  # x, y, z jako float32 + intensity jako uint32


class LidarPointBuffer:
    """Bufor punktow lidaru o stalej pojemnosci (podawanej w bajtach), z
    parametryzowanym zachowaniem po zapelnieniu: nadpisywanie od najstarszych
    (ring) albo pelne czyszczenie i zapelnianie od nowa (reset)."""

    def __init__(
        self,
        capacity_bytes: int = 1_048_576,
        mode: LidarBufferOverwriteMode = LidarBufferOverwriteMode.RING,
    ):
        self.capacity_bytes = capacity_bytes
        self.capacity_points = max(1, capacity_bytes // LIDAR_POINT_SIZE_BYTES)
        self.mode = mode
        self._points: deque = deque(
            maxlen=self.capacity_points if mode is LidarBufferOverwriteMode.RING else None
        )

    def add_points(self, points: List[Tuple[float, float, float, int]]) -> None:
        for point in points:
            if self.mode is LidarBufferOverwriteMode.RESET and len(self._points) >= self.capacity_points:
                self._points.clear()
            self._points.append(point)

    def get_points(self) -> List[Tuple[float, float, float, int]]:
        return list(self._points)

    def clear(self) -> None:
        self._points.clear()

    def __len__(self) -> int:
        return len(self._points)


@dataclass
class BandDetectionState:
    both_detected: bool = False
    left: bool = False
    right: bool = False
    last_update: float = 0.0
    debug_frame: str = ""


@dataclass
class ColorDetectionState:
    detected: bool = False
    blue_ratio: float = 0.0
    last_update: float = 0.0
    debug_frame: str = ""
    blue_bboxes: List[Tuple[int, int, int, int]] = None
    yellow_bboxes: List[Tuple[int, int, int, int]] = None
    target_bbox: Optional[Tuple[int, int, int, int]] = None
    green_on_yellow_detected: bool = False

    def __post_init__(self):
        if self.blue_bboxes is None:
            self.blue_bboxes = []
        if self.yellow_bboxes is None:
            self.yellow_bboxes = []


@dataclass
class VoiceRecognitionState:
    """Ostatnio rozpoznane wypowiedzi z Voice (src/ai/voice.py), do
    wyswietlenia w zakladce Glos zamiast zasmiecania logow/terminala."""
    last_text: str = ""
    last_action: Optional[str] = None
    last_update: float = 0.0
    history: List[dict] = None

    def __post_init__(self):
        if self.history is None:
            self.history = []


@dataclass
class RobotPose:
    """Estymacja pozycji robota z SLAM (BreezySLAM/RMHC) - patrz workers/slam_worker.py."""
    x_m: float = 0.0
    y_m: float = 0.0
    theta_deg: float = 0.0


@dataclass
class RobotState:
    stream_enabled: bool = False
    audio_stream_enabled: bool = False
    last_frame: CameraFrame | None = None
    last_audio_chunk: AudioChunk | None = None
    last_ads1115_state: ADS1115State | None = None
    lidar_point_buffer: LidarPointBuffer | None = None
    encoder_state: EncoderState | None = None
    band_detection_state: BandDetectionState | None = None
    color_detection_state: ColorDetectionState | None = None
    voice_recognition_state: VoiceRecognitionState | None = None
    robot_pose: RobotPose | None = None
    follow_band_mode: bool = False
    follow_band_max_pwm: int = 1200