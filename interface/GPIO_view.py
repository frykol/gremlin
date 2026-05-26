import tkinter as tk
import tkinter.font as tkFont
import json
import asyncio


GPIO_PINS = {
    7: "GPIO4",
    11: "GPIO17",
    13: "GPIO27",
    15: "GPIO22",
    16: "GPIO23",
    18: "GPIO24",
    22: "GPIO25",
    29: "GPIO5",
    31: "GPIO6",
    32: "GPIO12",
    33: "GPIO13",
    36: "GPIO16",
    37: "GPIO26"
}


class GpioView(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)

        self.app = app  

        self.buttons = {}
        self.values = {}
        self.active_pin = None

        self.gpio_font = tkFont.Font(family="Arial", size=12, weight="bold")


        tk.Button(self, text="0", command=lambda: self.set_value(0)).place(
            relx=0.4, rely=0.05, relwidth=0.2, relheight=0.06
        )
        tk.Button(self, text="1", command=lambda: self.set_value(1)).place(
            relx=0.6, rely=0.05, relwidth=0.2, relheight=0.06
        )

        for pin in range(1, 41):

            row = (pin - 1) // 2
            col = 0 if pin % 2 == 1 else 1

            label = GPIO_PINS.get(pin, str(pin))

            btn = tk.Button(
                self,
                text=label,
                font=self.gpio_font,
                state="normal" if pin in GPIO_PINS else "disabled",
                command=lambda p=pin: self.set_active(p),
                anchor="center",
                padx=0,
                pady=0
            )

            btn.place(
                relx=0.4 + col * 0.2,
                rely=0.15 + row * 0.035,
                relwidth=0.2,
                relheight=0.045
            )

            self.buttons[pin] = btn
            self.values[pin] = 0

            self.update_button(pin)


    def send_gpio(self):
        if self.active_pin is None:
            return

        data = {
            "type": "gpio",
            "pin_name": GPIO_PINS[self.active_pin],
            "value": self.values[self.active_pin]
        }

        for ws in self.app.clients:
            asyncio.run_coroutine_threadsafe(
                ws.send(json.dumps(data)),
                self.app.loop
            )


    def set_active(self, pin):
        if pin not in GPIO_PINS:
            return

        self.active_pin = pin

        for p, btn in self.buttons.items():
            btn.config(relief="sunken" if p == pin else "raised")

    def set_value(self, value):
        if self.active_pin is None:
            return

        self.values[self.active_pin] = value
        self.update_button(self.active_pin)

        self.send_gpio()

    def update_button(self, pin):
        v = self.values[pin]
        color = "#00ff00" if v == 1 else "#ff3333"
        self.buttons[pin].config(bg=color)