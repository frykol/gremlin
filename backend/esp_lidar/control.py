"""UDP command client for the ESP LiDAR control protocol."""

import random
import socket
import struct
import time
from collections.abc import Iterable, Callable

ESP_COMMAND_IP = "192.168.50.10"
ESP_COMMAND_PORT = 5006
TIMEOUT_S = 1.0
RETRIES = 3

MAGIC = b"LIDR"
VERSION = 1
HEADER_SIZE = 32
MSG_COMMAND = 128
MSG_COMMAND_ACK = 129

HEADER = struct.Struct("<4sBBHIHHHHQI")
COMMAND_PAYLOAD = struct.Struct("<IIII")
ACK_PAYLOAD = struct.Struct("<IIII")


def make_request_id() -> int:
    return ((time.monotonic_ns() >> 10) ^ random.getrandbits(32)) & 0xFFFFFFFF


def encode_command(request_id: int, command_id: int, args: Iterable[int]) -> bytes:
    values = list(args)[:4]
    values.extend([0] * (4 - len(values)))
    header = HEADER.pack(
        MAGIC,
        VERSION,
        MSG_COMMAND,
        HEADER_SIZE,
        request_id,
        command_id,
        0,
        COMMAND_PAYLOAD.size,
        0,
        0,
        0,
    )
    return header + COMMAND_PAYLOAD.pack(*values)


def decode_ack(data: bytes, expected_request_id: int) -> dict | None:
    if len(data) != HEADER_SIZE + ACK_PAYLOAD.size:
        return None

    (
        magic,
        version,
        message_type,
        header_size,
        request_id,
        command_id,
        result,
        payload_size,
        _field18,
        timestamp_us,
        _reserved,
    ) = HEADER.unpack_from(data)
    if (
        magic != MAGIC
        or version != VERSION
        or message_type != MSG_COMMAND_ACK
        or header_size != HEADER_SIZE
        or request_id != expected_request_id
        or payload_size != ACK_PAYLOAD.size
    ):
        return None

    state_flags, stream_mask, command_count, uptime_ms = ACK_PAYLOAD.unpack_from(
        data, HEADER_SIZE
    )
    return {
        "request_id": request_id,
        "command_id": command_id,
        "result": result,
        "timestamp_us": timestamp_us,
        "lidar_active": bool(state_flags & 0x01),
        "fusion_enabled": bool(state_flags & 0x02),
        "stream_mask": stream_mask,
        "command_count": command_count,
        "uptime_ms": uptime_ms,
    }


class EspControlClient:
    def __init__(
        self,
        host: str = ESP_COMMAND_IP,
        port: int = ESP_COMMAND_PORT,
        timeout: float = TIMEOUT_S,
        retries: int = RETRIES,
        socket_factory: Callable = socket.socket,
    ):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.retries = retries
        self.socket_factory = socket_factory

    def send(self, command_id: int, args: Iterable[int] = ()) -> dict:
        request_id = make_request_id()
        packet = encode_command(request_id, command_id, args)
        sock = self.socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            for attempt in range(self.retries):
                sock.sendto(packet, (self.host, self.port))
                deadline = time.monotonic() + self.timeout
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    sock.settimeout(remaining)
                    try:
                        data, address = sock.recvfrom(256)
                    except (socket.timeout, TimeoutError):
                        break
                    if address[0] != self.host:
                        continue
                    ack = decode_ack(data, request_id)
                    if ack is not None:
                        return ack
        finally:
            sock.close()
        raise TimeoutError(f"ESP {self.host}:{self.port} did not answer")