import tkinter as tk
import json
import asyncio

class ControlView(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app  

        # Mapowanie kierunków na konkretne kanały
        self.directions = {
            "Przód": [0, 2, 5, 7],
            "Tył":   [1, 3, 4, 6],
            "Prawo": [0, 2, 4, 6],
            "Lewo":  [1, 3, 5, 7]
        }

        self.active_directions = set()
        
        # Pamięć ostatnio wysłanego stanu (zapobiega spamowaniu sieci)
        # Inicjalizujemy wartościami -1, aby pierwszy wysłany stan (nawet same zera) zawsze przeszedł
        self.last_sent_values = {i: -1 for i in range(8)}
        
        # Etykieta statusu w oknie aplikacji
        self.status_label = tk.Label(
            self, text="NIEAKTYWNY", bg="red", fg="white", 
            font=("Arial", 14, "bold"), relief="ridge", bd=4
        )
        self.status_label.place(relx=0.3, rely=0.02, relwidth=0.6, relheight=0.12)

        # Suwak regulacji mocy
        self.power_slider = tk.Scale(
            self, from_=0, to=100, orient="horizontal", 
            label="Moc silników (%)", command=self.on_slider_change
        )
        self.power_slider.set(100) 
        self.power_slider.place(relx=0.3, rely=0.16, relwidth=0.6, relheight=0.15)

        # Tworzenie przycisków interfejsu
        self.buttons = {}
        coords = {"Przód": (0.5, 0.35), "Tył": (0.5, 0.65), "Lewo": (0.3, 0.50), "Prawo": (0.7, 0.50)}
        for name, (rx, ry) in coords.items():
            btn = tk.Button(self, text=name)
            btn.place(relx=rx, rely=ry, relwidth=0.2, relheight=0.15)
            btn.bind("<ButtonPress-1>", lambda e, d=name: self.on_press(d))
            btn.bind("<ButtonRelease-1>", lambda e, d=name: self.on_release(d))
            self.buttons[name] = btn

        # Bindy klawiatury
        top = self.winfo_toplevel()
        keys = {"<KeyPress-Up>": "Przód", "<KeyRelease-Up>": "Przód", 
                "<KeyPress-Down>": "Tył", "<KeyRelease-Down>": "Tył",
                "<KeyPress-Left>": "Lewo", "<KeyRelease-Left>": "Lewo",
                "<KeyPress-Right>": "Prawo", "<KeyRelease-Right>": "Prawo"}
        for key, name in keys.items():
            if "Press" in key:
                top.bind(key, lambda e, d=name: self.on_press(d))
            else:
                top.bind(key, lambda e, d=name: self.on_release(d))

    def get_current_pwm(self):
        return int((self.power_slider.get() / 100.0) * 4095)

    def send_motor_data(self, channel, pwm):
        data = {"type": "motor", "channel": channel, "pwm": pwm}
        for ws in self.app.clients:
            asyncio.run_coroutine_threadsafe(ws.send(json.dumps(data)), self.app.loop)

    def update_all_motors(self):
        pwm_val = self.get_current_pwm()
        
        # Pary kanałów dla silników: (kanał_przód, kanał_tył, nazwa_silnika)
        motor_pairs = [
            (0, 1, "M1 (Lewy Przód)"),
            (2, 3, "M2 (Lewy Tył)  "),
            (5, 4, "M3 (Prawy Przód)"),
            (7, 6, "M4 (Prawy Tył) ")
        ]
        
        channel_values = {i: 0 for i in range(8)}
        diagnostic_rows = []
        
        # Obliczamy wypadkowy sygnał dla każdego silnika
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

        # BLOKADA DUPLIKATÓW: Jeśli stan się nie zmienił, przerywamy funkcję
        if channel_values == self.last_sent_values:
            return

        # Zapamiętujemy nowy stan jako wysłany
        self.last_sent_values = channel_values.copy()

        # WIZUALNY WIDOK TESTOWY W KONSOLI (wykona się tylko przy realnej zmianie)
        print("\n=================== MONITOR SYGNAŁÓW TESTOWYCH ===================")
        print(f"Aktywne klawisze/kierunki : {list(self.active_directions) if self.active_directions else 'BRAK'}")
        print(f"Aktualna moc maksymalna    : {self.power_slider.get()}% (PWM: {pwm_val})")
        print("------------------------------------------------------------------")
        for row in diagnostic_rows:
            print(row)
        print("===================================================================\n")

        # Wysyłanie danych do sterownika
        for ch, pwm in channel_values.items():
            self.send_motor_data(ch, pwm)

    def on_press(self, direction):
        if direction in self.active_directions:
            return
        self.active_directions.add(direction)
        self.status_label.config(text=f"AKTYWNE: {','.join(self.active_directions)}", bg="green")
        self.update_all_motors()

    def on_release(self, direction):
        if direction not in self.active_directions:
            return
        self.active_directions.remove(direction)
        if not self.active_directions:
            self.status_label.config(text="NIEAKTYWNY", bg="red")
        else:
            self.status_label.config(text=f"AKTYWNE: {','.join(self.active_directions)}", bg="green")
        self.update_all_motors()

    def on_slider_change(self, value):
        self.update_all_motors()