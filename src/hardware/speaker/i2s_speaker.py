import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from .interface import SpeakerInterface, PlaybackState


class I2SSpeaker(SpeakerInterface):
    def __init__(self, alsa_device: str = "plughw:CARD=sndrpihifiberry,DEV=0"):
        """
        Initialize I2S speaker.

        Args:
            alsa_device: ALSA device name for the I2S sound card (GPIO 18-21).
        """
        self.alsa_device = alsa_device
        self.current_file: Optional[str] = None
        self.is_playing = False
        self.start_time: Optional[float] = None

        self._process: Optional[subprocess.Popen] = None
        self._decoder_process: Optional[subprocess.Popen] = None
        self._playback_lock = threading.Lock()
        self._playback_thread: Optional[threading.Thread] = None

        print(f"I2SSpeaker initialized on ALSA device {alsa_device}")

    def play(self, file_path: str, volume: float = 1.0) -> bool:
        """Play audio file asynchronously. Supports MP3 and WAV.

        Args:
            volume: linear gain applied via ffmpeg's volume filter (0.0-1.0+).
        """
        if not Path(file_path).exists():
            print(f"Error: File not found: {file_path}")
            return False

        volume = max(0.0, volume)

        with self._playback_lock:
            self._stop_playback()

            try:
                ffmpeg = subprocess.Popen(
                    [
                        "ffmpeg",
                        "-loglevel", "error",
                        "-i", file_path,
                        "-filter:a", f"volume={volume}",
                        "-f", "wav",
                        "-",
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                process = subprocess.Popen(
                    ["aplay", "-q", "-D", self.alsa_device],
                    stdin=ffmpeg.stdout,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                ffmpeg.stdout.close()
                self._decoder_process = ffmpeg
            except Exception as e:
                print(f"Error starting playback of {file_path}: {e}")
                return False

            self._process = process
            self.current_file = file_path
            self.is_playing = True
            self.start_time = time.monotonic()

            self._playback_thread = threading.Thread(
                target=self._wait_for_completion,
                args=(process,),
                daemon=True,
            )
            self._playback_thread.start()

        print(f"Playing: {file_path}")
        return True

    def stop(self) -> None:
        """Stop current playback."""
        with self._playback_lock:
            self._stop_playback()

    def get_state(self) -> PlaybackState:
        """Get current playback state."""
        with self._playback_lock:
            is_playing = self.is_playing
            current_file = self.current_file
            position = time.monotonic() - self.start_time if (is_playing and self.start_time) else 0.0

        return PlaybackState(
            is_playing=is_playing,
            current_file=current_file,
            position=position,
        )

    def _wait_for_completion(self, process: subprocess.Popen):
        """Wait for aplay to exit. Runs in background thread."""
        stderr = process.communicate()[1]

        with self._playback_lock:
            if self._process is process:
                if process.returncode not in (0, None) and stderr:
                    print(f"Playback error: {stderr.decode(errors='replace').strip()}")
                self.is_playing = False
                self.current_file = None
                self._process = None
                self._decoder_process = None

        print("Playback finished")

    def _stop_playback(self):
        """Internal stop without locking (must be called within lock)."""
        for proc in (self._decoder_process, self._process):
            if proc is None:
                continue
            try:
                proc.terminate()
                proc.wait(timeout=1)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        self._process = None
        self._decoder_process = None
        self.is_playing = False
        self.current_file = None
        self.start_time = None
