from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import numpy as np

@dataclass
class AudioChunk:
    samples: np.ndarray
    timestamp: float
    sample_rate: int
    channels: int
    chunk_id: int


@dataclass
class AudioFilterConfig:
    """Parametry filtrow notch tlumiacych szum mechaniczny (lidar/silniki) w
    sygnale mikrofonu. Domyslne wartosci odpowiadaja pasmom 150-235 Hz i
    360-470 Hz uzywanym pierwotnie na sztywno w reduce_noise_audio - center +-
    width/2 daje te same granice. Regulowane na zywo z zakladki Mikrofon,
    bo te pasma pokrywaja sie z pasmem mowy (F0/F1) i optymalna szerokosc
    zalezy od konkretnego egzemplarza sprzetu."""
    lidar_center_hz: float = 192.5
    lidar_width_hz: float = 85.0
    lidar_enabled: bool = True
    motor_center_hz: float = 415.0
    motor_width_hz: float = 110.0
    motor_enabled: bool = True


@dataclass
class NoiseProfileStatus:
    """Stan adaptacyjnej redukcji szumu (noisereduce) opartej o recznie
    zebrany profil szumu tla - patrz NoiseProfileReducer w respeaker.py.
    Uzupelnia statyczne filtry notch (AudioFilterConfig), ktore nie radza
    sobie z szerokopasmowym szumem silnikow/lidaru."""
    is_calibrating: bool = False
    has_profile: bool = False


class MicArrayInterface(ABC):
    @abstractmethod
    def start(self) -> None:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass

    @abstractmethod
    def get_audio_chunk(self) -> Optional[AudioChunk]:
        pass

    @abstractmethod
    def get_filter_config(self) -> AudioFilterConfig:
        pass

    @abstractmethod
    def update_filter_config(self, config: AudioFilterConfig) -> None:
        pass

    @abstractmethod
    def start_noise_profile_calibration(self) -> None:
        pass

    @abstractmethod
    def stop_noise_profile_calibration(self) -> None:
        pass

    @abstractmethod
    def reset_noise_profile(self) -> None:
        pass

    @abstractmethod
    def get_noise_profile_status(self) -> NoiseProfileStatus:
        pass
