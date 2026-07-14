import socket
import struct

HEADER_FORMAT = "!IHHd"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


class UdpFrameSender:
    def __init__(self, host: str, port: int, chunk_size: int = 1400):
        self.host = host
        self.port = port
        self.chunk_size = max(1, chunk_size - HEADER_SIZE)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def set_target(self, host: str, port: int) -> None:
        self.host = host
        self.port = port

    def send_frame(self, frame_id: int, timestamp: float, payload: bytes) -> None:
        total_chunks = max(1, (len(payload) + self.chunk_size - 1) // self.chunk_size)

        for chunk_index in range(total_chunks):
            start = chunk_index * self.chunk_size
            chunk = payload[start:start + self.chunk_size]

            header = struct.pack(
                HEADER_FORMAT,
                frame_id & 0xFFFFFFFF,
                chunk_index,
                total_chunks,
                timestamp,
            )

            self._socket.sendto(header + chunk, (self.host, self.port))

    def close(self) -> None:
        self._socket.close()
