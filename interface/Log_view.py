import tkinter as tk
from tkinter import scrolledtext
import os

class LogView(tk.Frame):
    def __init__(self, parent, app, log_path):
        super().__init__(parent)
        self.app = app
        self.log_path = log_path
        self._last_content = ""

        control_frame = tk.Frame(self, bg="#2e2e2e", height=40)
        control_frame.pack(fill="x", side="top")
        control_frame.pack_propagate(False)

        clear_btn = tk.Button(
            control_frame, text="Wyczyść Logi", command=self.clear_logs,
            bg="#d9534f", fg="white", relief="flat", font=("Arial", 10, "bold")
        )
        clear_btn.pack(side="left", padx=10, pady=5)

        self.text_area = scrolledtext.ScrolledText(
            self, wrap=tk.WORD, state="disabled", bg="#1e1e1e", fg="#f1f1f1", font=("Consolas", 10)
        )
        self.text_area.pack(fill="both", expand=True, padx=10, pady=10)

        self.text_area.tag_config("INFO", foreground="#4caf50")
        self.text_area.tag_config("ERROR", foreground="#f44336")
        self.text_area.tag_config("SYSTEM", foreground="#2196f3")

    def update_from_file(self):
        if not os.path.exists(self.log_path):
            return

        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return
            
        if self._last_content == content:
            return
            
        self._last_content = content
        self.text_area.config(state="normal")
        self.text_area.delete("1.0", tk.END)
        
        for line in content.splitlines():
            upper_line = line.upper()
            if "ERROR" in upper_line or "CRITICAL" in upper_line:
                tag = "ERROR"
            elif "SYSTEM" in upper_line:
                tag = "SYSTEM"
            elif "INFO" in upper_line:
                tag = "INFO"
            else:
                tag = None
            self.text_area.insert(tk.END, line + "\n", tag)
            
        self.text_area.config(state="disabled")

    def clear_logs(self):
        try:
            with open(self.log_path, "w", encoding="utf-8") as f:
                f.write("")
        except Exception as e:
            print(f"Błąd czyszczenia pliku: {e}")
            
        self._last_content = ""
        self.text_area.config(state="normal")
        self.text_area.delete("1.0", tk.END)
        self.text_area.config(state="disabled")