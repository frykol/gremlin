"""
Bufor akumulacyjny chmury punktow: pojedynczy ScanFrame ma do 120 punktow
(jeden aux+dist packet z lidaru), pelny ksztalt 3D wymaga akumulacji wielu
skanow w oknie czasowym - inaczej chmura wyglada plasko/jak cienka wstazka
(potwierdzone empirycznie na analogicznym pipeline MAVLink).
"""

import math
import time
from collections import deque
from dataclasses import dataclass
from typing import List, Optional

from .frame_parser import ScanFrame


@dataclass
class AccumulatedPoint:
    x: float
    y: float
    z: float
    intensity: float
    received_at: float


class PointAccumulator:
    def __init__(self, window_seconds: float = 3.0, max_range_m: float = 8.0):
        self.window_seconds = window_seconds
        self.max_range_m = max_range_m
        self._points: "deque[AccumulatedPoint]" = deque()

    def add_scan(self, scan: ScanFrame, now: Optional[float] = None) -> None:
        now = now if now is not None else time.monotonic()
        for x, y, z, intensity, _t, _ring in scan.points:
            distance = math.sqrt(x * x + y * y + z * z)
            if distance > self.max_range_m:
                continue
            self._points.append(AccumulatedPoint(x, y, z, intensity, now))
        self._evict_old(now)

    def _evict_old(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._points and self._points[0].received_at < cutoff:
            self._points.popleft()

    def prune(self, now: Optional[float] = None) -> None:
        """
        Usuwa punkty starsze niz okno, niezaleznie od naplywu nowych skanow.

        Bez tego okno czasowe jest czyszczone tylko w add_scan, wiec gdy
        zrodlo danych umiera (padniety bridge, koniec nagrania) chmura
        zostaje zamrozona na zawsze - dokladnie ten stan "wyglada ze dziala,
        a nie dziala", ktorego spec zabrania.
        """
        self._evict_old(now if now is not None else time.monotonic())

    def snapshot(self) -> List[AccumulatedPoint]:
        return list(self._points)

    def __len__(self) -> int:
        """Liczba punktow w oknie bez kopiowania/alokacji (patrz metrics_loop)."""
        return len(self._points)
