import tkinter as tk

class GpioView(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        tk.Label(self, text="GPIO").pack()
        tk.Button(self, text="Toggle pin").pack()