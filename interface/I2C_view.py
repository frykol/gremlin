import tkinter as tk

class I2CView(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        tk.Label(self, text="I2C").pack()
        tk.Button(self, text="Scan bus").pack()