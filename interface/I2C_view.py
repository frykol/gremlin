import tkinter as tk
import json
import asyncio


class I2CView(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)

        self.app = app  # 🔥 dostęp do servera

        self.buttons = []
        self.values = [0] * 16
        self.active_index = 0

        # SLIDER 0–100 (mapowany na 0–4095)
        self.slider = tk.Scale(
            self,
            from_=0,
            to=100,
            orient="horizontal",
            command=self.on_change
        )
        self.slider.place(relx=0.3, rely=0.05, relwidth=0.6, relheight=0.05)

        # PRZYCISKI
        for i in range(16):
            btn = tk.Button(
                self,
                text=str(i),
                command=lambda i=i: self.set_active(i)
            )

            row = i // 4
            col = i % 4

            btn.place(
                relx=0.4 + col * 0.1,
                rely=0.15 + row * 0.15,
                relwidth=0.08,
                relheight=0.1
            )

            self.buttons.append(btn)
            self.update_button(i)

        self.slider.set(0)

    # ================= SEND =================

    def send_motor(self):
        data = {
            "type": "motor",
            "channel": self.active_index,
            "pwm": int(self.slider.get() * 40.95)  # mapowanie
        }

        for ws in self.app.clients:
            asyncio.run_coroutine_threadsafe(
                ws.send(json.dumps(data)),
                self.app.loop
            )

    # ================= UI =================

    def set_active(self, index):
        self.active_index = index

        for i, btn in enumerate(self.buttons):
            btn.config(relief="sunken" if i == index else "raised")

        self.slider.set(self.values[index])

    def on_change(self, value):
        v = int(float(value))

        self.values[self.active_index] = v
        self.update_button(self.active_index)

        # 🔥 wysyłka do Raspberry
        self.send_motor()

    def update_button(self, index):
        v = self.values[index]
        color = self.value_to_color(v)
        self.buttons[index].config(bg=color)

    def value_to_color(self, v):
        r = 255 - int(v * 2.55)
        g = int(v * 2.55)
        b = 50
        return f"#{r:02x}{g:02x}{b:02x}"