import tkinter as tk

class CameraView(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        self.screen = tk.Frame(self,bg="lightblue",borderwidth=3,relief="ridge")
        self.screen.place(relx=0.3,rely=0.05,relheight=0.7,relwidth=0.6)

        self.oak_d_button = tk.Button(self,text="OAK_D")
        self.oak_d_button.place(relx=0.3,rely=0.75,relheight=0.2,relwidth=0.3)
        self.lidar_button = tk.Button(self,text="Lidar")
        self.lidar_button.place(relx=0.6,rely=0.75,relheight=0.2,relwidth=0.3)
        
        self.start_button = tk.Button(self,text="Start")
        self.start_button.place(relx=0.9,rely=0.05,relheight=0.05,relwidth=0.1)
        self.stop_button = tk.Button(self,text="Stop")
        self.stop_button.place(relx = 0.9,rely=0.1,relheight=0.05,relwidth=0.1)
        self.capture_button = tk.Button(self,text="Capture")
        self.capture_button.place(relx = 0.9, rely=0.15,relheight=0.05,relwidth=0.1)