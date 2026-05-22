import tkinter as tk
import base64
import asyncio
import json
import queue
import threading

import numpy as np

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except OSError:
    HAS_SOUNDDEVICE = False


class MicView(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)

        self.app = app
        self.sample_rate = 16000
        self.playback_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=32)
        self.playback_thread: threading.Thread | None = None
        self.playback_running = False
        self.level_var = tk.StringVar(value="0%")

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

        status = "sounddevice OK" if HAS_SOUNDDEVICE else "brak sounddevice — tylko poziom"
        tk.Label(self, text=status).place(relx=0.3, rely=0.68)

    def send_audio_stream(self, enabled: bool):
        data = {
            "type": "audio_stream",
            "enabled": enabled,
        }

        for ws in self.app.clients:
            asyncio.run_coroutine_threadsafe(
                ws.send(json.dumps(data)),
                self.app.loop,
            )

    def start_stream(self):
        self.send_audio_stream(True)
        self.start_playback()

    def stop_stream(self):
        self.send_audio_stream(False)
        self.stop_playback()

    def start_playback(self):
        if not HAS_SOUNDDEVICE or not self.playback_var.get():
            return
        if self.playback_running:
            return

        self.playback_running = True
        self.playback_thread = threading.Thread(target=self._playback_loop, daemon=True)
        self.playback_thread.start()

    def stop_playback(self):
        self.playback_running = False
        while not self.playback_queue.empty():
            try:
                self.playback_queue.get_nowait()
            except queue.Empty:
                break

    def _playback_loop(self):
        while self.playback_running:
            try:
                samples = self.playback_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if not self.playback_var.get():
                continue

            audio = samples.astype(np.float32) / 32768.0
            sd.play(audio, self.sample_rate, blocking=True)

    def update_audio(self, data):
        try:
            pcm = base64.b64decode(data["samples"])
            samples = np.frombuffer(pcm, dtype=np.int16)

            self.sample_rate = data.get("sample_rate", self.sample_rate)

            peak = int(np.max(np.abs(samples))) if samples.size else 0
            level = min(100, int(peak / 32768 * 100))
            self.level_var.set(f"chunk {data.get('chunk_id', '?')} | poziom {level}%")

            self._draw_level(level)

            if self.playback_var.get() and HAS_SOUNDDEVICE:
                try:
                    self.playback_queue.put_nowait(samples.copy())
                except queue.Full:
                    pass

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

        self.level_canvas.create_rectangle(
            0, h - bar_h, w, h,
            fill=color,
            outline="",
        )
        self.level_canvas.create_text(
            w // 2, h // 2,
            text=f"{level}%",
            fill="white",
            font=("Arial", 24, "bold"),
        )
