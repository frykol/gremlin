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
            "Lewo":  [1, 3, 5, 7]
        }

        self.current_active = None

        # Prostokąt statusu
        self.status_label = tk.Label(
            self, 
            text="NIEAKTYWNY", 
            bg="red", 
            fg="white", 
            font=("Arial", 14, "bold"),
            relief="ridge",
            bd=4
        )
        self.status_label.place(relx=0.3, rely=0.02, relwidth=0.6, relheight=0.12)

        # Suwak procentowej mocy silników (0-100%)
        self.power_slider = tk.Scale(
            self,
            from_=0,
            to=100,
            orient="horizontal",
            label="Moc silników (%)",
            command=self.on_slider_change
        )
        self.power_slider.set(100) # Domyślnie 100%
        self.power_slider.place(relx=0.3, rely=0.16, relwidth=0.6, relheight=0.15)

        self.buttons = {}
        self.default_bg = self.cget("bg")

        # Przesunięto przyciski lekko w dół (rely) by zrobić miejsce na suwak
        self.buttons["Przód"] = tk.Button(self, text="Przód")
        self.buttons["Przód"].place(relx=0.5, rely=0.35, relwidth=0.2, relheight=0.15)

        self.buttons["Tył"] = tk.Button(self, text="Tył")
        self.buttons["Tył"].place(relx=0.5, rely=0.65, relwidth=0.2, relheight=0.15)

        self.buttons["Lewo"] = tk.Button(self, text="Lewo")
        self.buttons["Lewo"].place(relx=0.3, rely=0.50, relwidth=0.2, relheight=0.15)

        self.buttons["Prawo"] = tk.Button(self, text="Prawo")
        self.buttons["Prawo"].place(relx=0.7, rely=0.50, relwidth=0.2, relheight=0.15)

        # Bindowanie myszki do przycisków
        for direction, btn in self.buttons.items():
            btn.bind("<ButtonPress-1>", lambda e, d=direction: self.on_press(d))
            btn.bind("<ButtonRelease-1>", lambda e, d=direction: self.on_release(d))

        # Bindowanie klawiatury (strzałek) do głównego okna aplikacji
        top_level = self.winfo_toplevel()
        
        top_level.bind("<KeyPress-Up>", lambda e: self.on_press("Przód"))
        top_level.bind("<KeyRelease-Up>", lambda e: self.on_release("Przód"))
        
        top_level.bind("<KeyPress-Down>", lambda e: self.on_press("Tył"))
        top_level.bind("<KeyRelease-Down>", lambda e: self.on_release("Tył"))
        
        top_level.bind("<KeyPress-Left>", lambda e: self.on_press("Lewo"))
        top_level.bind("<KeyRelease-Left>", lambda e: self.on_release("Lewo"))
        
        top_level.bind("<KeyPress-Right>", lambda e: self.on_press("Prawo"))
        top_level.bind("<KeyRelease-Right>", lambda e: self.on_release("Prawo"))

    def get_current_pwm(self):
        """Przelicza procenty z suwaka na wartość PWM (max 4095)."""
        percent = self.power_slider.get()
        return int((percent / 100.0) * 4095)

    def send_motor_data(self, channel, pwm):
        data = {
            "type": "motor",
            "channel": channel,
            "pwm": pwm
        }
        for ws in self.app.clients:
            asyncio.run_coroutine_threadsafe(
                ws.send(json.dumps(data)),
                self.app.loop
            )

    def stop_all_motors(self):
        for i in range(8):
            self.send_motor_data(i, 0)

    def on_press(self, direction):
        # Blokada przed ciągłym wysyłaniem sygnału przez automatyczne powtarzanie klawiszy
        if self.current_active == direction:
            return
        
        self.stop_all_motors()
        self.current_active = direction
        
        self.buttons[direction].config(bg="#a6a6a6", relief="sunken")
        
        self.status_label.config(
            text=f"AKTYWNY ({direction.upper()})", 
            bg="green"
        )
        
        channels = self.directions[direction]
        pwm_val = self.get_current_pwm()
        
        print(f"[+] Wciśnięto przycisk/klawisz: {direction.upper()}")
        print(f"    Aktywowane kanały: {channels} | Wartość PWM: {pwm_val} ({self.power_slider.get()}%)")
        print(f"    Wysyłanie sygnałów do klientów...")
        print("-" * 40)
        
        for ch in channels:
            self.send_motor_data(ch, pwm_val)

    def on_release(self, direction):
        # Sprawdzamy, czy puszczony klawisz to ten, który obecnie napędza robota
        if self.current_active != direction:
            return
            
        self.current_active = None
        self.stop_all_motors()
        
        self.buttons[direction].config(bg=self.default_bg, relief="raised")
        
        self.status_label.config(
            text="NIEAKTYWNY", 
            bg="red"
        )

        print(f"[-] Puszczono przycisk/klawisz: {direction.upper()}")
        print(f"    Wysłano sygnał stopu (PWM: 0) na wszystkie 8 kanałów.")
        print("-" * 40)

    def on_slider_change(self, value):
        """Aktualizuje moc silników w locie, jeśli zmieniasz suwak podczas jazdy."""
        if self.current_active:
            pwm_val = self.get_current_pwm()
            channels = self.directions[self.current_active]
            for ch in channels:
                self.send_motor_data(ch, pwm_val)