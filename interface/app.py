import tkinter as tk
import asyncio
import threading
import websockets
import json
import struct
import time

from Camera_view import CameraView
from Mic_view import MicView
from GPIO_view import GpioView
from I2C_view import I2CView
from Control_view import ControlView


class UDPCameraProtocol(asyncio.DatagramProtocol):

    def __init__(self, app):
        self.app = app
        self.buffers = {}            
        self.latest_frame_id = -1
        self.timeout_duration = 0.5  

    def datagram_received(self, data, addr):
        if len(data) < 16:
            return  

        header = data[:16]
        payload = data[16:]
        
        try:
            frame_id, chunk_index, total_chunks, timestamp = struct.unpack("!IHHd", header)
        except Exception as e:
            print(f"UDP Header parse error: {e}")
            return

        current_time = time.time()

        if frame_id > self.latest_frame_id:
            old_frames = [fid for fid in self.buffers if fid < frame_id]
            for fid in old_frames:
                del self.buffers[fid]
            self.latest_frame_id = frame_id
        elif frame_id < self.latest_frame_id:
            return  

        expired_frames = [fid for fid, info in self.buffers.items() if current_time - info["created_at"] > self.timeout_duration]
        for fid in expired_frames:
            del self.buffers[fid]

        if frame_id not in self.buffers:
            self.buffers[frame_id] = {
                "chunks": {},
                "total": total_chunks,
                "created_at": current_time
            }

        self.buffers[frame_id]["chunks"][chunk_index] = payload
        frame_info = self.buffers[frame_id]

        if len(frame_info["chunks"]) == frame_info["total"]:
            try:
                full_jpeg_bytes = b"".join(frame_info["chunks"][i] for i in range(frame_info["total"]))
                
                self.app.after(0, self.app.frames["camera"].update_frame, full_jpeg_bytes)
            except Exception as e:
                print(f"Error assembling frame {frame_id}: {e}")
            finally:
                del self.buffers[frame_id]


class App(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Interface")
        self.geometry("1600x800")

        self.clients = set()
        self.loop = asyncio.new_event_loop()

        container = tk.Frame(self)
        container.pack(fill="both", expand=True)

        self.frames = {}

        self.frames["camera"] = CameraView(container, self)
        self.frames["mic"] = MicView(container, self)
        self.frames["gpio"] = GpioView(container, self)
        self.frames["i2c"] = I2CView(container, self)
        self.frames["control"] = ControlView(container, self)

        for frame in self.frames.values():
            frame.place(relwidth=1, relheight=1)

        sidebar = tk.Frame(self, bg="gray")
        sidebar.place(relx=0, rely=0, relwidth=0.2, relheight=1)

        tk.Button(sidebar, text="Camera", command=lambda: self.show("camera")).pack(fill="x")
        tk.Button(sidebar, text="Mikrofon", command=lambda: self.show("mic")).pack(fill="x")
        tk.Button(sidebar, text="GPIO", command=lambda: self.show("gpio")).pack(fill="x")
        tk.Button(sidebar, text="I2C PWM", command=lambda: self.show("i2c")).pack(fill="x")
        tk.Button(sidebar, text="Control", command=lambda: self.show("control")).pack(fill="x")

        self.status_label = tk.Label(
            sidebar, 
            text="Łączący się", 
            bg="yellow", 
            fg="black", 
            font=("Arial", 11, "bold"),
            pady=10
        )
        self.status_label.pack(side="bottom", fill="x", pady=10, padx=10)

        threading.Thread(target=self.start_ws, daemon=True).start()

        self.show("camera")

    def show(self, name):
        self.frames[name].tkraise()

    def update_status(self, status):
        if status == "connecting":
            self.status_label.config(text="Łączący się", bg="yellow", fg="black")
        elif status == "connected":
            self.status_label.config(text="Połączony", bg="green", fg="white")
        elif status == "disconnected":
            self.status_label.config(text="Rozłączony", bg="red", fg="white")

    def start_ws(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.ws_server())

    async def handler(self, websocket):
        self.clients.add(websocket)
        self.after(0, self.update_status, "connected")
        print("Client connected:", websocket.remote_address)

        try:
            async for msg in websocket:
                data = json.loads(msg)

                if data.get("type") == "audio_chunk":
                    self.after(0, self.frames["mic"].update_audio, data)
                else:
                    print("RX:", data)

        except Exception as e:
            print("WS error:", e)

        finally:
            self.clients.remove(websocket)
            print("Client disconnected")
            if not self.clients:
                self.after(0, self.update_status, "disconnected")

    async def ws_server(self):
        try:
            with open("config.json", "r") as f:
                config = json.load(f)
            udp_port = config.get("camera_stream", {}).get("udp_port", 8766)
        except Exception:
            udp_port = 8766

        udp_endpoint = self.loop.create_datagram_endpoint(
            lambda: UDPCameraProtocol(self),
            local_addr=("0.0.0.0", udp_port)
        )
        transport, protocol = await udp_endpoint
        print(f"UDP Stream listener connected on port {udp_port}")

        try:
            async with websockets.serve(self.handler, "0.0.0.0", 8765):
                print("WebSocket server running on 8765")
                self.after(0, self.update_status, "disconnected")
                await asyncio.Future()
        except Exception as e:
            print(f"Server error: {e}")
            self.after(0, self.update_status, "disconnected")


if __name__ == "__main__":
    App().mainloop()