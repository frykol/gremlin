import tkinter as tk
import base64
import asyncio
import json
import threading
import wave
import time
import numpy as np

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except OSError:
    HAS_SOUNDDEVICE = False


class AudioRingBuffer:
    def __init__(self, capacity_samples: int):
        self._buf = np.zeros(capacity_samples, dtype=np.float32)
        self._capacity = capacity_samples
        self._write = 0
        self._read = 0
        self._available = 0
        self._lock = threading.Lock()

    def write(self, samples: np.ndarray) -> None:
        audio = samples.astype(np.float32) / 32768.0

        with self._lock:
            n = len(audio)
            if n >= self._capacity:
                audio = audio[-self._capacity:]
                n = self._capacity
                self._read = 0
                self._write = 0
                self._available = 0

            first = min(n, self._capacity - self._write)
            self._buf[self._write:self._write + first] = audio[:first]

            rest = n - first
            if rest > 0:
                self._buf[:rest] = audio[first:]

            self._write = (self._write + n) % self._capacity
            self._available = min(self._capacity, self._available + n)

    def read(self, frames: int, out: np.ndarray) -> None:
        with self._lock:
            to_read = min(frames, self._available)

            if to_read == 0:
                out.fill(0)
                return

            first = min(to_read, self._capacity - self._read)
            out[:first] = self._buf[self._read:self._read + first]

            rest = to_read - first
            if rest > 0:
                out[first:to_read] = self._buf[:rest]

            self._read = (self._read + to_read) % self._capacity
            self._available -= to_read

            if to_read < frames:
                out[to_read:] = 0


class MicView(tk.Frame):
    OUTPUT_BLOCKSIZE = 512

    def __init__(self, parent, app):
        super().__init__(parent)

        self.app = app
        self.sample_rate = 16000
        self.level_var = tk.StringVar(value="0%")

        self._streaming = False
        self._ring: AudioRingBuffer | None = None
        self._output_stream = None
        self._audio_lock = threading.Lock()
        
        # Zmienne do nagrywania
        self.recording_var = tk.BooleanVar(value=False)
        self._wave_file = None
        self._current_filename = None
        self._start_record_time = None
        self._timer_running = False

        self.screen = tk.Frame(self, bg="black", borderwidth=3, relief="ridge")
        self.screen.place(relx=0.3, rely=0.05, relheight=0.55, relwidth=0.6)

        self.level_canvas = tk.Canvas(self.screen, bg="black", highlightthickness=0)
        self.level_canvas.pack(fill="both", expand=True)

        self.info_label = tk.Label(self, textvariable=self.level_var, font=("Arial", 14))
        self.info_label.place(relx=0.3, rely=0.62, relwidth=0.6)

        self.start_button = tk.Button(self, text="Start", command=self.start_stream)
        self.start_button.place(relx=0.9, rely=0.05, relheight=0.05, relwidth=0.1)

        self.stop_button = tk.Button(self, text="Stop", command=self.stop_stream)
        self.stop_button.place(relx=0.9, rely=0.1, relheight=0.05, relwidth=0.1)

        self.playback_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            self,
            text="Odsłuch",
            variable=self.playback_var,
        ).place(relx=0.9, rely=0.15)

        tk.Checkbutton(
            self,
            text="Nagrywanie (.wav)",
            variable=self.recording_var,
        ).place(relx=0.9, rely=0.20)

        # Label z czasem nagrywania
        self.timer_label = tk.Label(self, text="Czas: 0s", font=("Arial", 10, "bold"), fg="red")
        self.timer_label.place(relx=0.9, rely=0.25)

        status = "sounddevice OK" if HAS_SOUNDDEVICE else "brak sounddevice — tylko poziom"
        tk.Label(self, text=status).place(relx=0.3, rely=0.68)

    def _start_recording(self):
        """Inicjalizacja pliku i timera."""
        self._current_filename = f"recording_{int(time.time())}.wav"
        self._wave_file = wave.open(self._current_filename, 'wb')
        self._wave_file.setnchannels(1)
        self._wave_file.setsampwidth(2)
        self._wave_file.setframerate(self.sample_rate)
        
        self._start_record_time = time.time()
        self._timer_running = True
        self.update_timer()
        print(f"Nagrywanie rozpoczęte: {self._current_filename}")

    def _stop_recording(self):
        """Zamykanie pliku i zatrzymanie timera."""
        if self._wave_file:
            self._wave_file.close()
            self._wave_file = None
            self._timer_running = False
            self.timer_label.config(text="Czas: 0s")
            print(f"Nagrywanie zatrzymane. Plik zapisany jako: {self._current_filename}")
            self._current_filename = None

    def update_timer(self):
        if self._timer_running:
            elapsed = int(time.time() - self._start_record_time)
            self.timer_label.config(text=f"Czas: {elapsed}s")
            self.after(1000, self.update_timer)

    def send_audio_stream(self, enabled: bool):
        data = {"type": "audio_stream", "enabled": enabled}
        for ws in self.app.clients:
            asyncio.run_coroutine_threadsafe(ws.send(json.dumps(data)), self.app.loop)

    def start_stream(self):
        self._streaming = True
        self.send_audio_stream(True)
        self.start_playback()
        
        # Start nagrywania jeśli checkbox zaznaczony
        if self.recording_var.get():
            self._start_recording()

    def stop_stream(self):
        self._streaming = False
        self.send_audio_stream(False)
        self.stop_playback()
        
        # Stop nagrywania jeśli trwało
        if self._wave_file:
            self._stop_recording()

    def _audio_callback(self, outdata, frames, _time, _status):
        ring = self._ring
        if ring is None:
            outdata.fill(0)
            return
        ring.read(frames, outdata[:, 0])

    def start_playback(self):
        if not HAS_SOUNDDEVICE or not self.playback_var.get():
            return
        with self._audio_lock:
            if self._output_stream is not None:
                return
        def _open():
            with self._audio_lock:
                if self._output_stream is not None or not self._streaming:
                    return
                self._ring = AudioRingBuffer(self.sample_rate)
                stream = sd.OutputStream(
                    samplerate=self.sample_rate,
                    channels=1,
                    dtype="float32",
                    blocksize=self.OUTPUT_BLOCKSIZE,
                    callback=self._audio_callback,
                )
                stream.start()
                self._output_stream = stream
        threading.Thread(target=_open, daemon=True).start()

    def stop_playback(self):
        with self._audio_lock:
            stream = self._output_stream
            self._output_stream = None
            self._ring = None
        if stream is None:
            return
        def _close():
            try:
                stream.stop()
                stream.close()
            except Exception as e:
                print("Playback stop error:", e)
        threading.Thread(target=_close, daemon=True).start()

    def update_audio(self, data):
        if not self._streaming:
            return
        try:
            pcm = base64.b64decode(data["samples"])
            
            if self._wave_file:
                self._wave_file.writeframes(pcm)

            samples = np.frombuffer(pcm, dtype=np.int16)
            sample_rate = data.get("sample_rate", self.sample_rate)
            if sample_rate != self.sample_rate:
                self.sample_rate = sample_rate
                self.stop_playback()
                if self._streaming:
                    self.start_playback()

            peak = int(np.max(np.abs(samples))) if samples.size else 0
            level = min(100, int(peak / 32768 * 100))
            self.level_var.set(f"chunk {data.get('chunk_id', '?')} | poziom {level}%")
            self._draw_level(level)

            ring = self._ring
            if self.playback_var.get() and HAS_SOUNDDEVICE and ring is not None:
                ring.write(samples)
        except Exception as e:
            print("Audio frame error:", e)

    def _draw_level(self, level: int):
        self.level_canvas.delete("all")
        w = self.level_canvas.winfo_width()
        h = self.level_canvas.winfo_height()
        if w <= 1 or h <= 1:
            return
        bar_h = int(h * level / 100)
        color = "#00ff00" if level < 70 else "#ffaa00" if level < 90 else "#ff3333"
        self.level_canvas.create_rectangle(0, h - bar_h, w, h, fill=color, outline="")
        self.level_canvas.create_text(w // 2, h // 2, text=f"{level}%", fill="white", font=("Arial", 24, "bold"))