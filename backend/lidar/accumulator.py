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
    def __init__(
        self,
        window_seconds: float = 3.0,
        max_range_m: float = 8.0,
        max_points: Optional[int] = None,
    ):
        """
        max_points: ring buffer capacity (deque z maxlen) - gdy podane,
        punkty NIE znikaja przedwczesnie z powodu wieku, tylko zostaja
        nadpisane (FIFO) dopiero po zapelnieniu bufora, tak jak w ring
        bufferze frontendu (site/public/lidar/js/pointcloud.js). Bez tego
        (max_points=None, domyslnie) zachowanie jest jak wczesniej - czysto
        czasowe okno.
        """
        self.window_seconds = window_seconds
        self.max_range_m = max_range_m
        self.max_points = max_points
        self._points: "deque[AccumulatedPoint]" = deque(maxlen=max_points)

    def add_scan(self, scan: ScanFrame, now: Optional[float] = None) -> None:
        now = now if now is not None else time.monotonic()
        for x, y, z, intensity, _t, _ring in scan.points:
            distance = math.sqrt(x * x + y * y + z * z)
            if distance > self.max_range_m:
                continue
            # Z maxlen ustawionym, append() sam nadpisuje najstarszy element
            # gdy bufor jest pelny (FIFO ring buffer) - to glowny mechanizm
            # usuwania podczas normalnej pracy zrodla danych. _evict_old
            # ponizej zostaje jako bezpiecznik na wypadek martwego zrodla
            # (patrz prune()) - przy dlugim window_seconds nie koliduje z
            # ring bufferem w normalnej pracy.
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
