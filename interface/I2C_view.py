import tkinter as tk
import json
import asyncio


class I2CView(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)

        self.app = app  

        self.buttons = []
        self.values = [0] * 8  
        self.active_index = 0

        labels = [
            "LP przód", "LP tył",
            "LT przód", "LT tył",
            "PP tył", "PP przód",
            "PT tył", "PT przód"
        ]

        self.slider = tk.Scale(
            self,
            from_=0,
            to=100,
            orient="horizontal",
            command=self.on_change
        )
        self.slider.place(relx=0.3, rely=0.05, relwidth=0.6, relheight=0.05)

        tk.Button(self, text="0", command=lambda: self.slider.set(0)).place(
            relx=0.4, rely=0.15, relwidth=0.2, relheight=0.06
        )
        tk.Button(self, text="1", command=lambda: self.slider.set(100)).place(
            relx=0.6, rely=0.15, relwidth=0.2, relheight=0.06
        )

        for i, label_text in enumerate(labels):
            btn = tk.Button(
                self,
                text=label_text,
                command=lambda i=i: self.set_active(i)
            )

            row = i // 2
            col = i % 2

            btn.place(
                relx=0.4 + col * 0.2,
                rely=0.25 + row * 0.1,
                relwidth=0.2,
                relheight=0.1
            )

            self.buttons.append(btn)
            self.update_button(i)

        self.slider.set(0)


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

    def send_motor_stop(self, channel):
        data = {
            "type": "motor",
            "channel": channel,
            "pwm": 0
        }

        for ws in self.app.clients:
            asyncio.run_coroutine_threadsafe(
                ws.send(json.dumps(data)),
                self.app.loop
            )


    def set_active(self, index):
        self.active_index = index

        for i, btn in enumerate(self.buttons):
            btn.config(relief="sunken" if i == index else "raised")

        self.slider.set(self.values[index])

    def on_change(self, value):
        v = int(float(value))

        if v > 0:

            opposite_index = self.active_index ^ 1 
            
            if self.values[opposite_index] > 0:

                self.values[opposite_index] = 0
                self.update_button(opposite_index)
                

                self.send_motor_stop(opposite_index)


        self.values[self.active_index] = v
        self.update_button(self.active_index)

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