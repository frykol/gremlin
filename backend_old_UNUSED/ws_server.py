"""
Kodowanie ramek binarnych/JSON wysylanych do przegladarki przez WS oraz
rejestr podlaczonych klientow z broadcastem.

WAZNE: wszystkie naglowki maja rozmiar bedacy wielokrotnoscia 4 bajtow, bo
JS Float32Array rzuca RangeError, jesli byteOffset nie jest wielokrotnoscia
4 - stad uint32 (nie uint8) na pole "type".
"""

import asyncio
import json
import logging
import struct
from typing import Iterable, Tuple, Union

logger = logging.getLogger("lidar_viewer")

SCAN_WS_TYPE = 1
IMU_WS_TYPE = 2

# Sentinel w ramce metryk: "opoznienia nie da sie sensownie zmierzyc"
# (tryb replay - stamp pochodzi z nagrania, albo brak jeszcze ramki IMU).
# Frontend renderuje wtedy "N/A" zamiast liczby udajacej pomiar.
LATENCY_NOT_AVAILABLE = -1.0

_SCAN_HEADER_FMT = "<II"  # type, pointCount
_IMU_FMT = "<I10f"  # type + quat(4) + angvel(3) + linacc(3)


def encode_scan_frame(points: Iterable[Tuple[float, float, float, float]]) -> bytes:
    points = list(points)
    header = struct.pack(_SCAN_HEADER_FMT, SCAN_WS_TYPE, len(points))
    if not points:
        return header
    flat = [v for point in points for v in point]
    body = struct.pack(f"<{len(flat)}f", *flat)
    return header + body


def encode_imu_frame(
    quaternion: Tuple[float, float, float, float],
    angular_velocity: Tuple[float, float, float],
    linear_acceleration: Tuple[float, float, float],
) -> bytes:
    return struct.pack(
        _IMU_FMT,
        IMU_WS_TYPE,
        *quaternion,
        *angular_velocity,
        *linear_acceleration,
    )


def encode_metrics_frame(fps: float, points_in_window: int, latency_ms: float) -> str:
    return json.dumps(
        {
            "type": "metrics",
            "fps": fps,
            "points_in_window": points_in_window,
            "latency_ms": latency_ms,
        }
    )


class ClientRegistry:
    def __init__(self):
        self._clients = set()

    def add(self, ws) -> None:
        self._clients.add(ws)

    def remove(self, ws) -> None:
        self._clients.discard(ws)

    async def broadcast(self, message: Union[bytes, str]) -> None:
        stale = []
        for ws in list(self._clients):
            try:
                await ws.send(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Celowo szeroko: broadcast_loop to `while True` w tle, wiec
                # KAZDY wyciekajacy wyjatek (nie tylko ConnectionClosed)
                # zabija broadcast na stale - bez zadnego widocznego objawu
                # poza tracebackiem w handlerze petli zdarzen. Wypadniecie
                # jednego klienta nie moze zatrzymac pipeline'u dla reszty.
                logger.warning("Blad wysylki do klienta WS, usuwam go: %r", exc)
                stale.append(ws)
        for ws in stale:
            self._clients.discard(ws)
