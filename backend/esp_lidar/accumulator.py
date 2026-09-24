"""Skladanie ostatniej pelnej ramki punktow ESP LiDAR."""

from typing import List, Tuple

Point = Tuple[float, float, float, float]  # x, y, z, intensity


class PointFrameAccumulator:
    def __init__(self):
        self._frame_id = None
        self._packet_count = 0
        self._packets = {}
        self._points: List[Point] = []

    def add_packet(
        self,
        frame_id: int,
        packet_id: int,
        packet_count: int,
        points: List[Tuple[float, float, float, int]],
    ) -> None:
        if self._frame_id is not None and frame_id < self._frame_id:
            return
        if self._frame_id != frame_id or self._packet_count != packet_count:
            self._frame_id = frame_id
            self._packet_count = packet_count
            self._packets = {}

        self._packets.setdefault(
            packet_id,
            [(x, y, z, float(intensity)) for x, y, z, intensity in points],
        )
        if len(self._packets) == self._packet_count:
            self._points = [
                point
                for packet_id in sorted(self._packets)
                for point in self._packets[packet_id]
            ]

    def snapshot(self) -> List[Point]:
        return list(self._points)

    def __len__(self) -> int:
        return len(self._points)
