import tkinter as tk
from tkinter import scrolledtext
from datetime import datetime

class LogView(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app

        control_frame = tk.Frame(self, bg="#2e2e2e", height=40)
        control_frame.pack(fill="x", side="top")
        control_frame.pack_propagate(False)

        clear_btn = tk.Button(
            control_frame, 
            text="Wyczyść Logi", 
            command=self.clear_logs,
            bg="#d9534f", 
            fg="white", 
            relief="flat",
            font=("Arial", 10, "bold"),
            padx=10
        )
        clear_btn.pack(side="left", padx=10, pady=5)

        self.text_area = scrolledtext.ScrolledText(
            self, 
            wrap=tk.WORD, 
            state="disabled",
            bg="#1e1e1e", 
            fg="#f1f1f1",
            insertbackground="white",
            font=("Consolas", 10)
        )
        self.text_area.pack(fill="both", expand=True, padx=10, pady=10)

        self.text_area.tag_config("INFO", foreground="#4caf50")
        self.text_area.tag_config("ERROR", foreground="#f44336")
        self.text_area.tag_config("SYSTEM", foreground="#2196f3")

    def _safe_append(self, message, level):
        timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        full_msg = f"{timestamp} [{level}] {message}\n"

        self.text_area.config(state="normal")
        self.text_area.insert(tk.END, full_msg, level)
        self.text_area.see(tk.END)
        self.text_area.config(state="disabled")

    def clear_logs(self):
        self.text_area.config(state="normal")
        self.text_area.delete("1.0", tk.END)
        self.text_area.config(state="disabled")