import time
from typing import Optional

import numpy as np
from scipy import signal

from .interface import MicArrayInterface, AudioChunk

USB_VENDOR_ID = 0x2886
USB_PRODUCT_ID = 0x0018
DEFAULT_DEVICE_NAME = "ReSpeaker 4 Mic Array"

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

        samples_out = reduce_noise_audio(samples, self.sample_rate)

        return AudioChunk(
            samples=samples_out,
            timestamp=time.time(),
            sample_rate=self.sample_rate,
            channels=1,
            chunk_id=self.chunk_id,
        )


def reduce_noise_audio(y: np.ndarray, sample_rate: int) -> np.ndarray:
    if y is None:
        return y

    y = np.asarray(y, dtype=np.float32)
    y = np.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0)

    lidar_low = 150.0
    lidar_high = 235.0
    motor_low = 360.0
    motor_high = 470.0

    lidar_sos = signal.butter(8, [lidar_low, lidar_high], btype="bandstop", fs=sample_rate, output="sos")
    y = signal.sosfiltfilt(lidar_sos, y)

    motor_sos = signal.butter(8, [motor_low, motor_high], btype="bandstop", fs=sample_rate, output="sos")
    y = signal.sosfiltfilt(motor_sos, y)

    y = np.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0)

    return y
