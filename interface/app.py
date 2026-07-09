import tkinter as tk
import asyncio
import threading
import websockets
import json
import struct
import time
import sys
import base64
import os

from Camera_view import CameraView
from Mic_view import MicView
from GPIO_view import GpioView
from I2C_view import I2CView
from Control_view import ControlView
from Log_view import LogView

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE_PATH = os.path.join(BASE_DIR, "host.log")

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
            print(f"UDP Header parse error: {e}", file=sys.stderr)
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
        
        if len(self.buffers[frame_id]["chunks"]) == self.buffers[frame_id]["total"]:
            try:
                full_jpeg_bytes = b"".join(self.buffers[frame_id]["chunks"][i] for i in range(self.buffers[frame_id]["total"]))
                self.app.after(0, self.app.frames["camera"].update_frame, full_jpeg_bytes)
            except Exception as e:
                print(f"Error assembling frame {frame_id}: {e}", file=sys.stderr)
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
        self.frames["log"] = LogView(container, self, LOG_FILE_PATH)

        for name, frame in self.frames.items():
            if name == "log":
                frame.place(relx=0.2, rely=0, relwidth=0.8, relheight=1)
            else:
                frame.place(relx=0, rely=0, relwidth=1, relheight=1)

        sidebar = tk.Frame(self, bg="gray")
        sidebar.place(relx=0, rely=0, relwidth=0.2, relheight=1)

        tk.Button(sidebar, text="Camera", command=lambda: self.show("camera")).pack(fill="x")
        tk.Button(sidebar, text="Mikrofon", command=lambda: self.show("mic")).pack(fill="x")
        tk.Button(sidebar, text="GPIO", command=lambda: self.show("gpio")).pack(fill="x")
        tk.Button(sidebar, text="I2C PWM", command=lambda: self.show("i2c")).pack(fill="x")
        tk.Button(sidebar, text="Control", command=lambda: self.show("control")).pack(fill="x")
        tk.Button(sidebar, text="Log", command=lambda: self.show("log")).pack(fill="x")

        # --- SEKCJA PROGRAM I INDYKATORÓW ---
        
        # Indykatory statusu
        self.status_label = tk.Label(sidebar, text="Łączący się", bg="yellow", fg="black", font=("Arial", 11, "bold"), pady=10)
        self.status_label.pack(side="bottom", fill="x", pady=10, padx=10)

        self.program_status_label = tk.Label(sidebar, text="Nieznany", bg="gray", fg="white", font=("Arial", 11, "bold"), pady=10)
        self.program_status_label.pack(side="bottom", fill="x", pady=(0, 5), padx=10)

        # Przyciski sterujące
        control_frame = tk.Frame(sidebar, bg="gray")
        control_frame.pack(side="bottom", fill="x", pady=(0, 10), padx=10)
        
        tk.Label(control_frame, text="Program:", bg="gray", fg="white").pack()
        btn_frame = tk.Frame(control_frame, bg="gray")
        btn_frame.pack(fill="x")
        
        tk.Button(btn_frame, text="ON", command=lambda: self.send_program_command("on")).pack(side="left", expand=True, fill="x")
        tk.Button(btn_frame, text="OFF", command=lambda: self.send_program_command("off")).pack(side="left", expand=True, fill="x")

        threading.Thread(target=self.start_ws, daemon=True).start()
        self.show("camera")
        self.poll_host_logs()
        self.poll_program_status()

    def send_program_command(self, status):
        """Wysyła komendę ON/OFF przez WebSocket"""
        if self.clients:
            data = {"type": "set_program_status", "status": status}
            msg = json.dumps(data)
            for ws in self.clients:
                asyncio.run_coroutine_threadsafe(ws.send(msg), self.loop)

    def show(self, name):
        self.frames[name].tkraise()

    def update_status(self, status):
        if status == "connecting": self.status_label.config(text="Łączący się", bg="yellow", fg="black")
        elif status == "connected": self.status_label.config(text="Połączony", bg="green", fg="white")
        elif status == "disconnected": self.status_label.config(text="Rozłączony", bg="red", fg="white")

    def update_program_status(self, status):
        if status == "on":
            self.program_status_label.config(text="Program uruchomiony", bg="green", fg="white")
        elif status == "off":
            self.program_status_label.config(text="Program wyłączony", bg="red", fg="white")
        else:
            self.program_status_label.config(text="Nieznany", bg="gray", fg="white")

    def poll_host_logs(self):
        if self.clients:
            data = {"send": "logs"}
            msg = json.dumps(data)
            for ws in self.clients:
                asyncio.run_coroutine_threadsafe(ws.send(msg), self.loop)
        self.after(500, self.poll_host_logs)

    def poll_program_status(self):
        if self.clients:
            data = {"type": "get_program_status"}
            msg = json.dumps(data)
            for ws in self.clients:
                asyncio.run_coroutine_threadsafe(ws.send(msg), self.loop)
        else:
            self.after(0, self.update_program_status, "unknown")
        
        self.after(500, self.poll_program_status)

    def start_ws(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.ws_server())

    async def handler(self, websocket):
        self.clients.add(websocket)
        self.after(0, self.update_status, "connected")

        try:
            async for msg in websocket:
                try:
                    data = json.loads(msg)
                    msg_type = data.get("type")
                    b64_file = data.get("file")
                    
                    if b64_file is not None:
                        try:
                            decoded_text = base64.b64decode(b64_file).decode("utf-8")
                            with open(LOG_FILE_PATH, "w", encoding="utf-8") as f:
                                f.write(decoded_text + "\n")
                            self.after(0, self.frames["log"].update_from_file)
                        except Exception as decode_err:
                            print(f"File write error: {decode_err}", file=sys.stderr)
                    elif msg_type == "audio_chunk":
                        self.after(0, self.frames["mic"].update_audio, data)
                    elif msg_type == "get_program_status":
                        status = data.get("status")
                        self.after(0, self.update_program_status, status)
                except json.JSONDecodeError:
                    if isinstance(msg, str) and msg.strip():
                        with open(LOG_FILE_PATH, "w", encoding="utf-8") as f:
                            f.write(msg + "\n")
                        self.after(0, self.frames["log"].update_from_file)
        finally:
            self.clients.remove(websocket)
            if not self.clients:
                self.after(0, self.update_status, "disconnected")
                self.after(0, self.update_program_status, "unknown")

    async def ws_server(self):
        try:
            with open("config.json", "r") as f:
                config = json.load(f)
            udp_port = config.get("camera_stream", {}).get("udp_port", 8766)
        except:
            udp_port = 8766

        udp_endpoint = self.loop.create_datagram_endpoint(lambda: UDPCameraProtocol(self), local_addr=("0.0.0.0", udp_port))
        await udp_endpoint
        async with websockets.serve(self.handler, "0.0.0.0", 8765):
            await asyncio.Future()

if __name__ == "__main__":
    App().mainloop()