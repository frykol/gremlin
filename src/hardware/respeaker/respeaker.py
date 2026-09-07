import time
from collections import deque
from typing import Optional

import numpy as np
import noisereduce
from scipy import signal

from .interface import AudioFilterConfig, MicArrayInterface, AudioChunk, NoiseProfileStatus

USB_VENDOR_ID = 0x2886
USB_PRODUCT_ID = 0x0018
DEFAULT_DEVICE_NAME = "ReSpeaker 4 Mic Array"

NOTCH_FILTER_ORDER = 8
NOISE_PROFILE_PROCESS_BUFFER_CHUNKS = 4


class StreamingNoiseReducer:
    """Tlumi szum mechaniczny (lidar/silniki) filtrami notch, zachowujac
    stan filtra (zi) miedzy kolejnymi chunkami audio.

    Poprzednia wersja wywolywala scipy.signal.sosfiltfilt niezaleznie na
    kazdym 1024-probkowym chunku (~64ms) - kazde takie wywolanie zaklada
    zerowe warunki brzegowe, wiec na granicy kazdego chunku powstawal skok
    (zmierzony blad ~38% amplitudy), slyszalny jako trzaski i psujacy
    rozpoznawanie mowy przez caly czas nagrania. Ten filtr uzywa
    przyczynowego sosfilt z przenoszeniem zi z jednego wywolania do
    kolejnego, wiec sygnal jest filtrowany tak, jakby byl jednym ciaglym
    strumieniem."""

    def __init__(self, sample_rate: int, order: int = NOTCH_FILTER_ORDER):
        self.sample_rate = sample_rate
        self.order = order

        self._config = AudioFilterConfig()
        self._lidar_sos = None
        self._lidar_zi = None
        self._motor_sos = None
        self._motor_zi = None
        self.update_config(self._config)

    def get_config(self) -> AudioFilterConfig:
        return self._config

    def update_config(self, config: AudioFilterConfig) -> None:
        self._config = config

        if config.lidar_enabled:
            self._lidar_sos = self._build_sos(config.lidar_center_hz, config.lidar_width_hz)
            self._lidar_zi = signal.sosfilt_zi(self._lidar_sos)
        else:
            self._lidar_sos = None
            self._lidar_zi = None

        if config.motor_enabled:
            self._motor_sos = self._build_sos(config.motor_center_hz, config.motor_width_hz)
            self._motor_zi = signal.sosfilt_zi(self._motor_sos)
        else:
            self._motor_sos = None
            self._motor_zi = None

    def _build_sos(self, center_hz: float, width_hz: float):
        # width_hz=0 (suwak w UI ma min="0") dawal low == high, co scipy
        # odrzuca (ValueError: Wn[0] must be less than Wn[1]) - a poniewaz
        # process_commands() lapal tylko asyncio.QueueEmpty, ten wyjatek
        # ubijal cala petle obslugi komend na stale (patrz sim.log:
        # "Program manager not running, ignoring instruction" po kazdej
        # kolejnej komendzie, z dowolnej zakladki). Wymuszamy tu minimalna
        # sensowna szerokosc pasma zamiast pozwolic na degenerata.
        width_hz = max(1.0, width_hz)
        nyquist = self.sample_rate / 2.0
        low = max(1.0, center_hz - width_hz / 2.0)
        high = min(nyquist - 1.0, center_hz + width_hz / 2.0)
        if low >= high:
            low = max(1.0, high - 1.0)
        return signal.butter(self.order, [low, high], btype="bandstop", fs=self.sample_rate, output="sos")

    def apply(self, y: np.ndarray) -> np.ndarray:
        y = np.asarray(y, dtype=np.float32)
        y = np.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0)

        if self._lidar_sos is not None:
            y, self._lidar_zi = signal.sosfilt(self._lidar_sos, y, zi=self._lidar_zi)

        if self._motor_sos is not None:
            y, self._motor_zi = signal.sosfilt(self._motor_sos, y, zi=self._motor_zi)

        return np.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0)


class NoiseProfileReducer:
    """Adaptacyjna redukcja szumu (noisereduce, spektralne bramkowanie)
    wzgledem recznie zebranego profilu szumu tla.

    StreamingNoiseReducer (filtry notch) tlumi tylko dwa wąskie,
    zalozone z gory pasma - dziala jedynie na czysto tonalny szum na
    stalej czestotliwosci. Szum silnikow/lidaru w praktyce jest w duzej
    mierze szerokopasmowy, wiec notche same w sobie nie daja czystego
    dzwieku bez ryzyka wyciecia tez mowy. Ten filtr uczy sie prawdziwego
    widma szumu z probki nagranej na zadanie ("Skalibruj szum" w
    zakladce Mikrofon, gdy w otoczeniu jest tylko szum tla) i tlumi w
    widmie tylko to, co faktycznie tam jest.

    Przetwarzanie dzieje sie na wiekszych buforach (chunk_size *
    NOISE_PROFILE_PROCESS_BUFFER_CHUNKS probek) zamiast na kazdym 64ms
    chunku z osobna - spektralne bramkowanie pojedynczego, krotkiego
    chunku dawaloby podobny problem z artefaktami na granicach, jaki
    mielismy wczesniej z filtrem notch per-chunk. Kosztem jest niewielkie
    dodatkowe opoznienie (rzedu kilkuset ms), akceptowalne dla komend
    glosowych."""

    def __init__(self, sample_rate: int, chunk_size: int, buffer_chunks: int = NOISE_PROFILE_PROCESS_BUFFER_CHUNKS):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.process_buffer_samples = chunk_size * buffer_chunks

        self._calibrating = False
        self._calibration_samples: list[np.ndarray] = []
        self._noise_profile: Optional[np.ndarray] = None

        self._raw_buffer = np.zeros(0, dtype=np.float32)
        self._output_queue: "deque[np.ndarray]" = deque()

    @property
    def has_profile(self) -> bool:
        return self._noise_profile is not None

    @property
    def is_calibrating(self) -> bool:
        return self._calibrating

    def get_status(self) -> NoiseProfileStatus:
        return NoiseProfileStatus(is_calibrating=self._calibrating, has_profile=self.has_profile)

    def start_calibration(self) -> None:
        self._calibrating = True
        self._calibration_samples = []

    def stop_calibration(self) -> None:
        self._calibrating = False
        if self._calibration_samples:
            self._noise_profile = np.concatenate(self._calibration_samples)
        self._calibration_samples = []
        self._raw_buffer = np.zeros(0, dtype=np.float32)
        self._output_queue.clear()

    def reset_profile(self) -> None:
        self._noise_profile = None
        self._raw_buffer = np.zeros(0, dtype=np.float32)
        self._output_queue.clear()

    def process(self, chunk: np.ndarray) -> np.ndarray:
        chunk = np.asarray(chunk, dtype=np.float32)
        chunk = np.nan_to_num(chunk, nan=0.0, posinf=0.0, neginf=0.0)

        if self._calibrating:
            self._calibration_samples.append(chunk.copy())
            return chunk

        if self._noise_profile is None:
            return chunk

        self._raw_buffer = np.concatenate([self._raw_buffer, chunk])

        while len(self._raw_buffer) >= self.process_buffer_samples:
            block = self._raw_buffer[:self.process_buffer_samples]
            self._raw_buffer = self._raw_buffer[self.process_buffer_samples:]

            denoised = noisereduce.reduce_noise(
                y=block,
                sr=self.sample_rate,
                y_noise=self._noise_profile,
                stationary=True,
                use_tqdm=False,
                n_jobs=1,
            )
            for i in range(0, len(denoised), self.chunk_size):
                self._output_queue.append(denoised[i:i + self.chunk_size])

        if self._output_queue:
            return self._output_queue.popleft()

        # Bufor jeszcze sie nie zapelnil - zwracamy cisze zamiast
        # niefiltrowanego surowego dzwieku, zeby nie przeciekal do
        # Vosk/odsluchu w trakcie zbierania danych do przetworzenia.
        return np.zeros(self.chunk_size, dtype=np.float32)


def find_device_index(device_name: str = DEFAULT_DEVICE_NAME) -> int:
    import sounddevice as sd

    devices = sd.query_devices()

    for index, device in enumerate(devices):
        if device_name in device["name"] and device["max_input_channels"] > 0:
            return index

    raise RuntimeError(f"Nie znaleziono urządzenia audio: {device_name}")

class ReSpeakerMicArray(MicArrayInterface):
    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 6,
        chunk_size: int = 1024,
        device_name: str = DEFAULT_DEVICE_NAME,
    ):
        self.sample_rate: int = sample_rate
        self.channels: int = channels
        self.chunk_size: int = chunk_size
        self.device_name: str = device_name

        self.running: bool = False
        self.chunk_id: int = 0

        self._stream = None
        self._noise_reducer = StreamingNoiseReducer(sample_rate)
        self._noise_profile_reducer = NoiseProfileReducer(sample_rate, chunk_size)

    def get_filter_config(self) -> AudioFilterConfig:
        return self._noise_reducer.get_config()

    def update_filter_config(self, config: AudioFilterConfig) -> None:
        self._noise_reducer.update_config(config)

    def start_noise_profile_calibration(self) -> None:
        self._noise_profile_reducer.start_calibration()

    def stop_noise_profile_calibration(self) -> None:
        self._noise_profile_reducer.stop_calibration()

    def reset_noise_profile(self) -> None:
        self._noise_profile_reducer.reset_profile()

    def get_noise_profile_status(self) -> NoiseProfileStatus:
        return self._noise_profile_reducer.get_status()

    def start(self) -> None:
        if self.running:
            return

        import sounddevice as sd

        device_index = find_device_index(self.device_name)

        self._stream = sd.InputStream(
            device=device_index,
            channels=self.channels,
            samplerate=self.sample_rate,
            blocksize=self.chunk_size,
            dtype=np.int16,
        )
        self._stream.start()

        self.running = True
        print("ReSpeaker mic array działa")

    def stop(self) -> None:
        self.running = False

        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        print("ReSpeaker mic array zatrzymana")

    def get_audio_chunk(self) -> Optional[AudioChunk]:
        if not self.running or self._stream is None:
            return None

        samples, _overflowed = self._stream.read(self.chunk_size)

        if samples.size == 0:
            return None

        self.chunk_id += 1

        if samples.ndim > 1:
            samples = samples[:, 0]

        samples_out = self._noise_reducer.apply(samples)
        samples_out = self._noise_profile_reducer.process(samples_out)

        return AudioChunk(
            samples=samples_out,
            timestamp=time.time(),
            sample_rate=self.sample_rate,
            channels=1,
            chunk_id=self.chunk_id,
        )
