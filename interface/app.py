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
    """
    Protokół UDP reasemblujący pofragmentowane klatki JPEG z robota.
    """
    def __init__(self, app):
        self.app = app
        self.buffers = {}            # frame_id -> {"chunks": {idx: bytes}, "total": int, "created_at": float}
        self.latest_frame_id = -1
        self.timeout_duration = 0.5  # Maksymalny czas na skompletowanie klatki (500ms)

    def datagram_received(self, data, addr):
        if len(data) < 16:
            return  # Pakiet za mały na nagłówek

        # Rozpakowanie nagłówka z network byte order (big-endian): !IHHd
        header = data[:16]
        payload = data[16:]
        
        try:
            frame_id, chunk_index, total_chunks, timestamp = struct.unpack("!IHHd", header)
        except Exception as e:
            print(f"UDP Header parse error: {e}")
            return

        current_time = time.time()

        # 1. Porzucanie starych, nieskompletowanych buforów, gdy nadchodzi nowszy frame_id
        if frame_id > self.latest_frame_id:
            old_frames = [fid for fid in self.buffers if fid < frame_id]
            for fid in old_frames:
                del self.buffers[fid]
            self.latest_frame_id = frame_id
        elif frame_id < self.latest_frame_id:
            return  # Ignoruj pakiety spóźnione chronologicznie

        # 2. Czyszczenie starych klatek, które przekroczyły timeout (np. przez utracone pakiety)
        expired_frames = [fid for fid, info in self.buffers.items() if current_time - info["created_at"] > self.timeout_duration]
        for fid in expired_frames:
            del self.buffers[fid]

        # 3. Inicjalizacja nowego bufora klatki
        if frame_id not in self.buffers:
            self.buffers[frame_id] = {
                "chunks": {},
                "total": total_chunks,
                "created_at": current_time
            }

        # Zapisanie fragmentu
        self.buffers[frame_id]["chunks"][chunk_index] = payload
        frame_info = self.buffers[frame_id]

        # 4. Sprawdzenie kompletności klatki
        if len(frame_info["chunks"]) == frame_info["total"]:
            try:
                # Scalenie klatki w całość zgodnie z kolejnością chunk_index
                full_jpeg_bytes = b"".join(frame_info["chunks"][i] for i in range(frame_info["total"]))
                
                # Bezpieczne przekazanie surowych bajtów do wątku głównego GUI Tkintera
                self.app.after(0, self.app.frames["camera"].update_frame, full_jpeg_bytes)
            except Exception as e:
                print(f"Error assembling frame {frame_id}: {e}")
            finally:
                # Usunięcie z pamięci po przetworzeniu
                del self.buffers[frame_id]


class App(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Interface")
        self.geometry("1600x800")

        self.clients = set()
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.start_ws, daemon=True).start()

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

        self.show("camera")

    def show(self, name):
        self.frames[name].tkraise()

    def start_ws(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.ws_server())

    async def handler(self, websocket):
        self.clients.add(websocket)
        print("Client connected:", websocket.remote_address)

        try:
            async for msg in websocket:
                data = json.loads(msg)

                # USUNIĘTO: 'camera_frame' z obsługi przez WS
                if data.get("type") == "audio_chunk":
                    self.after(0, self.frames["mic"].update_audio, data)
                else:
                    print("RX:", data)

        except Exception as e:
            print("WS error:", e)

        finally:
            self.clients.remove(websocket)
            print("Client disconnected")

    async def ws_server(self):
        # Pobranie portu UDP z config.json (lub fallback na 8766)
        try:
            with open("config.json", "r") as f:
                config = json.load(f)
            udp_port = config.get("camera_stream", {}).get("udp_port", 8766)
        except Exception:
            udp_port = 8766

        # Rejestracja serwera UDP w pętli asyncio
        udp_endpoint = self.loop.create_datagram_endpoint(
            lambda: UDPCameraProtocol(self),
            local_addr=("0.0.0.0", udp_port)
        )
        transport, protocol = await udp_endpoint
        print(f"UDP Stream listener connected on port {udp_port}")

        # Start serwera WebSocket
        async with websockets.serve(self.handler, "0.0.0.0", 8765):
            print("WebSocket server running on 8765")
            await asyncio.Future()


if __name__ == "__main__":
    App().mainloop()