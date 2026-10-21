"""Forward completed ESP LiDAR point frames to an optional UDP consumer."""

import socket
import struct
from collections.abc import Callable, Iterable

MAGIC = b"ELDP"
VERSION = 1
MSG_POINT_CLOUD = 1
HEADER_FORMAT = "<4sBBH IHHI"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
POINT_FORMAT = "<4f"
POINT_SIZE = struct.calcsize(POINT_FORMAT)
DEFAULT_MAX_DATAGRAM_SIZE = 1400
MAX_CHUNK_COUNT = 0xFFFF
MAX_UDP_PAYLOAD_SIZE = 65507


def _validate_max_datagram_size(max_datagram_size: int) -> None:
    if max_datagram_size < HEADER_SIZE + POINT_SIZE:
        raise ValueError(
            f"max_datagram_size must be at least {HEADER_SIZE + POINT_SIZE} bytes"
        )
    if max_datagram_size > MAX_UDP_PAYLOAD_SIZE:
        raise ValueError(f"max_datagram_size must not exceed {MAX_UDP_PAYLOAD_SIZE} bytes")


def encode_scan_datagrams(
    frame_id: int,
    points: Iterable[tuple[float, float, float, float]],
    max_datagram_size: int = DEFAULT_MAX_DATAGRAM_SIZE,
) -> list[bytes]:
    points = list(points)
    _validate_max_datagram_size(max_datagram_size)

    points_per_chunk = (max_datagram_size - HEADER_SIZE) // POINT_SIZE
    chunk_count = max(1, (len(points) + points_per_chunk - 1) // points_per_chunk)
    if chunk_count > MAX_CHUNK_COUNT:
        raise ValueError(f"point frame requires too many UDP datagrams: {chunk_count}")

    datagrams = []
    for chunk_index in range(chunk_count):
        start = chunk_index * points_per_chunk
        chunk = points[start:start + points_per_chunk]
        header = struct.pack(
            HEADER_FORMAT,
            MAGIC,
            VERSION,
            MSG_POINT_CLOUD,
            HEADER_SIZE,
            frame_id,
            chunk_index,
            chunk_count,
            len(points),
        )
        payload = b"".join(struct.pack(POINT_FORMAT, *point) for point in chunk)
        datagrams.append(header + payload)
    return datagrams


class PointCloudUdpForwarder:
    def __init__(
        self,
        host: str,
        port: int,
        max_datagram_size: int = DEFAULT_MAX_DATAGRAM_SIZE,
        socket_factory: Callable = socket.socket,
    ):
        if not host:
            raise ValueError("UDP forward destination host is required")
        if not 1 <= port <= 65535:
            raise ValueError("UDP forward destination port must be between 1 and 65535")
        _validate_max_datagram_size(max_datagram_size)
        self.destination = (host, port)
        self.max_datagram_size = max_datagram_size
        self._socket = socket_factory(socket.AF_INET, socket.SOCK_DGRAM)

    def send_frame(
        self,
        frame_id: int,
        points: Iterable[tuple[float, float, float, float]],
    ) -> None:
        for datagram in encode_scan_datagrams(
            frame_id, points, self.max_datagram_size
        ):
            self._socket.sendto(datagram, self.destination)

    def close(self) -> None:
        self._socket.close()