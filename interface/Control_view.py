import tkinter as tk
import json
import asyncio

class ControlView(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app  

        self.directions = {
            "Przód": [0, 2, 5, 7],
            "Tył":   [1, 3, 4, 6],
            "Prawo": [0, 2, 4, 6],
            "Lewo":  [1, 3, 5, 7],
            "Full lewo": [1, 2, 5, 6],
            "Full prawo": [0, 3, 4, 7]
        }

        self.active_directions = set()
        self.pressed_keys = set()
        self.pressed_buttons = set()
        self.key_release_timers = {}
        self.last_sent_values = {i: -1 for i in range(8)}
        
        self.status_label = tk.Label(
            self, text="NIEAKTYWNY", bg="red", fg="white", 
            font=("Arial", 14, "bold"), relief="ridge", bd=4
        )
        self.status_label.place(relx=0.3, rely=0.02, relwidth=0.6, relheight=0.12)

        self.power_slider = tk.Scale(
            self, from_=0, to=100, orient="horizontal", 
            label="Moc silników (%)", command=self.on_slider_change
        )
        self.power_slider.set(20) 
        self.power_slider.place(relx=0.3, rely=0.16, relwidth=0.6, relheight=0.15)

        self.buttons = {}
        coords = {
            "Przód":      (0.5, 0.35),
            "Lewo":       (0.3, 0.45),
            "Prawo":      (0.7, 0.45),
            "Full lewo":  (0.3, 0.60),
            "Full prawo": (0.7, 0.60),
            "Tył":        (0.5, 0.65)
        }
        
        for name, (rx, ry) in coords.items():
            btn = tk.Button(self, text=name, font=("Arial", 9, "bold") if "Full" in name else ("Arial", 9))
            btn.place(relx=rx, rely=ry, relwidth=0.16, relheight=0.12)
            btn.bind("<ButtonPress-1>", lambda e, d=name: self.on_btn_press(d))
            btn.bind("<ButtonRelease-1>", lambda e, d=name: self.on_btn_release(d))
            self.buttons[name] = btn

        top = self.winfo_toplevel()
        
        key_map = {
            "<KeyPress-Up>": "Up", "<KeyRelease-Up>": "Up",
            "<Shift-KeyPress-Up>": "Up", "<Shift-KeyRelease-Up>": "Up",
            "<KeyPress-Down>": "Down", "<KeyRelease-Down>": "Down",
            "<Shift-KeyPress-Down>": "Down", "<Shift-KeyRelease-Down>": "Down",
            "<KeyPress-Left>": "Left", "<KeyRelease-Left>": "Left",
            "<Shift-KeyPress-Left>": "Left", "<Shift-KeyRelease-Left>": "Left",
            "<KeyPress-Right>": "Right", "<KeyRelease-Right>": "Right",
            "<Shift-KeyPress-Right>": "Right", "<Shift-KeyRelease-Right>": "Right",
            "<KeyPress-Shift_L>": "Shift", "<KeyRelease-Shift_L>": "Shift",
            "<KeyPress-Shift_R>": "Shift", "<KeyRelease-Shift_R>": "Shift"
        }
        
        for ev, k in key_map.items():
            if "Press" in ev:
                top.bind(ev, lambda e, key_name=k: self.on_key_press(key_name))
            else:
                top.bind(ev, lambda e, key_name=k: self.on_key_release(key_name))

    def get_current_pwm(self):
        return int((self.power_slider.get() / 100.0) * 4095)

    def send_motor_data(self, channel, pwm):
        data = {"type": "motor", "channel": channel, "pwm": pwm}
        for ws in self.app.clients:
            asyncio.run_coroutine_threadsafe(ws.send(json.dumps(data)), self.app.loop)

    def update_all_motors(self):
        pwm_val = self.get_current_pwm()
        
        motor_pairs = [
            (0, 1, "M1 (Lewy Przód)"),
            (2, 3, "M2 (Lewy Tył)  "),
            (5, 4, "M3 (Prawy Przód)"),
            (7, 6, "M4 (Prawy Tył) ")
        ]
        
        channel_values = {i: 0 for i in range(8)}
        diagnostic_rows = []
        
        for f_ch, b_ch, motor_name in motor_pairs:
            net_signal = 0
            
            for direction in self.active_directions:
                if f_ch in self.directions[direction]:
                    net_signal += pwm_val
                if b_ch in self.directions[direction]:
                    net_signal -= pwm_val
            
            if net_signal > 0:
                channel_values[f_ch] = min(net_signal, pwm_val)
                channel_values[b_ch] = 0
                status = f"PRZÓD ({channel_values[f_ch]})"
            elif net_signal < 0:
                channel_values[f_ch] = 0
                channel_values[b_ch] = min(abs(net_signal), pwm_val)
                status = f"TYŁ ({channel_values[b_ch]})"
            else:
                channel_values[f_ch] = 0
                channel_values[b_ch] = 0
                status = "STOP (Zneutralizowany / Brak)"

            diagnostic_rows.append(
                f"{motor_name} -> Ch{f_ch}: {channel_values[f_ch]:<4} | Ch{b_ch}: {channel_values[b_ch]:<4} | Status: {status}"
            )

        if channel_values == self.last_sent_values:
            return

        self.last_sent_values = channel_values.copy()

        print("\n=================== MONITOR SYGNAŁÓW TESTOWYCH ===================")
        print(f"Aktywne klawisze/kierunki : {list(self.active_directions) if self.active_directions else 'BRAK'}")
        print(f"Aktualna moc maksymalna    : {self.power_slider.get()}% (PWM: {pwm_val})")
        print("------------------------------------------------------------------")
        for row in diagnostic_rows:
            print(row)
        print("===================================================================\n")

        for ch, pwm in channel_values.items():
            self.send_motor_data(ch, pwm)

    def on_key_press(self, key):
        if key in self.key_release_timers:
            self.after_cancel(self.key_release_timers[key])
            del self.key_release_timers[key]
            
        if key not in self.pressed_keys:
            self.pressed_keys.add(key)
            self.recalculate_directions()

    def on_key_release(self, key):
        if key in self.key_release_timers:
            self.after_cancel(self.key_release_timers[key])
            
        self.key_release_timers[key] = self.after(20, lambda: self._execute_key_release(key))

    def _execute_key_release(self, key):
        if key in self.key_release_timers:
            del self.key_release_timers[key]
            
        if key in self.pressed_keys:
            self.pressed_keys.remove(key)
            self.recalculate_directions()

    def on_btn_press(self, direction):
        if direction not in self.pressed_buttons:
            self.pressed_buttons.add(direction)
            self.recalculate_directions()

    def on_btn_release(self, direction):
        if direction in self.pressed_buttons:
            self.pressed_buttons.remove(direction)
            self.recalculate_directions()

    def recalculate_directions(self):
        new_directions = set(self.pressed_buttons)
        
        if "Up" in self.pressed_keys:
            new_directions.add("Przód")
        if "Down" in self.pressed_keys:
            new_directions.add("Tył")
            
        if "Left" in self.pressed_keys:
            if "Shift" in self.pressed_keys:
                new_directions.add("Full lewo")
            else:
                new_directions.add("Lewo")
                
        if "Right" in self.pressed_keys:
            if "Shift" in self.pressed_keys:
                new_directions.add("Full prawo")
            else:
                new_directions.add("Prawo")

        if new_directions != self.active_directions:
            self.active_directions = new_directions
            if not self.active_directions:
                self.status_label.config(text="NIEAKTYWNY", bg="red")
            else:
                self.status_label.config(text=f"AKTYWNE: {','.join(self.active_directions)}", bg="green")
            
            self.update_all_motors()

    def on_slider_change(self, value):
        self.update_all_motors()