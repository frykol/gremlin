import tkinter as tk

class CameraView(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        tk.Label(self, text="CAMERA").pack()
        tk.Button(self, text="Test camera").pack()