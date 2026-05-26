import tkinter as tk
import asyncio
import threading
import websockets
import json

from Camera_view import CameraView
from GPIO_view import GpioView
from I2C_view import I2CView


class App(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Interface")
        self.geometry("1600x800")

        # ================= WS SERVER =================
        self.clients = set()
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.start_ws, daemon=True).start()

        # ================= UI =================
        container = tk.Frame(self)
        container.pack(fill="both", expand=True)

        self.frames = {}

        self.frames["camera"] = CameraView(container, self)
        self.frames["gpio"] = GpioView(container, self)
        self.frames["i2c"] = I2CView(container, self)

        for frame in self.frames.values():
            frame.place(relwidth=1, relheight=1)

        # ================= SIDEBAR =================
        sidebar = tk.Frame(self, bg="gray")
        sidebar.place(relx=0, rely=0, relwidth=0.2, relheight=1)

        tk.Button(sidebar, text="Camera", command=lambda: self.show("camera")).pack(fill="x")
        tk.Button(sidebar, text="GPIO", command=lambda: self.show("gpio")).pack(fill="x")
        tk.Button(sidebar, text="I2C PWM", command=lambda: self.show("i2c")).pack(fill="x")

        self.show("camera")

    # ================= VIEW SWITCH =================

    def show(self, name):
        self.frames[name].tkraise()

    # ================= WS SERVER =================

    def start_ws(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.ws_server())

    async def handler(self, websocket):
        self.clients.add(websocket)
        print("Client connected:", websocket.remote_address)

        try:
            async for msg in websocket:
                data = json.loads(msg)

                # 🔥 CAMERA FRAME
                if data.get("type") == "camera_frame":
                    # ważne: Tkinter thread-safe
                    self.after(0, self.frames["camera"].update_frame, data)

                # DEBUG (opcjonalnie)
                else:
                    print("RX:", data)

        except Exception as e:
            print("WS error:", e)

        finally:
            self.clients.remove(websocket)
            print("Client disconnected")

    async def ws_server(self):
        async with websockets.serve(self.handler, "0.0.0.0", 8765):
            print("WebSocket server running on 8765")
            await asyncio.Future()


if __name__ == "__main__":
    App().mainloop()