import tkinter as tk
import base64
import asyncio
import json
from PIL import Image, ImageTk
import io
import time
import os


class CameraView(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)

        self.app = app
        self.last_frame = None  # 🔥 do zapisu

        # ================= SCREEN =================
        self.screen = tk.Frame(self, bg="lightblue", borderwidth=3, relief="ridge")
        self.screen.place(relx=0.3, rely=0.05, relheight=0.7, relwidth=0.6)

        self.image_label = tk.Label(self.screen)
        self.image_label.pack(fill="both", expand=True)

        # ================= BUTTONS =================
        self.oak_d_button = tk.Button(self, text="OAK_D")
        self.oak_d_button.place(relx=0.3, rely=0.75, relheight=0.2, relwidth=0.3)

        self.lidar_button = tk.Button(self, text="Lidar", state="disabled")
        self.lidar_button.place(relx=0.6, rely=0.75, relheight=0.2, relwidth=0.3)

        self.start_button = tk.Button(self, text="Start", command=self.start_stream)
        self.start_button.place(relx=0.9, rely=0.05, relheight=0.05, relwidth=0.1)

        self.stop_button = tk.Button(self, text="Stop", command=self.stop_stream)
        self.stop_button.place(relx=0.9, rely=0.1, relheight=0.05, relwidth=0.1)

        self.capture_button = tk.Button(self, text="Capture", command=self.capture_frame)
        self.capture_button.place(relx=0.9, rely=0.15, relheight=0.05, relwidth=0.1)

    # ================= WS SEND =================

    def send_stream(self, enabled):
        data = {
            "type": "stream",
            "enabled": enabled
        }

        for ws in self.app.clients:
            asyncio.run_coroutine_threadsafe(
                ws.send(json.dumps(data)),
                self.app.loop
            )

    def start_stream(self):
        self.send_stream(True)

    def stop_stream(self):
        self.send_stream(False)

    # ================= FRAME UPDATE =================

    def update_frame(self, data):
        try:
            # dekodowanie base64 → obraz
            img_data = base64.b64decode(data["image"])
            image = Image.open(io.BytesIO(img_data))

            # zapisz do capture
            self.last_frame = image

            # dopasowanie do okna
            w = self.screen.winfo_width()
            h = self.screen.winfo_height()

            if w > 0 and h > 0:
                image = image.resize((w, h))

            photo = ImageTk.PhotoImage(image)

            self.image_label.config(image=photo)
            self.image_label.image = photo  # ⚠️ konieczne

        except Exception as e:
            print("Frame error:", e)

    # ================= CAPTURE =================

    def capture_frame(self):
        if self.last_frame is None:
            print("No frame to save")
            return

        os.makedirs("captures", exist_ok=True)

        filename = f"captures/frame_{int(time.time())}.jpg"
        self.last_frame.save(filename)

        print("Saved:", filename)