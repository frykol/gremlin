import tkinter as tk

from Camera_view import CameraView
from GPIO_view import GpioView
from I2C_view import I2CView


class App(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("System")
        self.geometry("1600x800")

        container = tk.Frame(self)
        container.pack(fill="both", expand=True)

        self.frames = {}
        
        self.frames["camera"] = CameraView(container)
        self.frames["gpio"] = GpioView(container)
        self.frames["i2c"] = I2CView(container)

        for frame in self.frames.values():
            frame.place(relwidth=1, relheight=1)

        sidebar = tk.Frame(self, bg="gray")
        sidebar.place(relx=0, rely=0, relwidth=0.2, relheight=1)

        tk.Button(sidebar, text="Camera", command=lambda: self.show("camera")).pack(fill="x")
        tk.Button(sidebar, text="GPIO", command=lambda: self.show("gpio")).pack(fill="x")
        tk.Button(sidebar, text="I2C", command=lambda: self.show("i2c")).pack(fill="x")

        self.show("camera")

    def show(self, name):
        frame = self.frames[name]
        frame.tkraise()


if __name__ == "__main__":
    App().mainloop()