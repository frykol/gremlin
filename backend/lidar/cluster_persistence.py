"""
Utrzymuje wykryte klastry widoczne przez pewien czas, nawet gdy dany tick
klastrowania ich nie zwrocil (np. przez chwilowy szum, luke w danych albo
drobne przesuniecie granic klastra miedzy klatkami) - zamiast znikac
natychmiast, znikaja dopiero po braku potwierdzenia przez timeout_s.

WAZNE - czym to NIE jest: to NIE jest pelne sledzenie tozsamosci obiektow
(brak trwalego ID widocznego na zewnatrz, decyzja podjeta wczesniej w
rozmowie - "tylko pojedyncza klatka"). To prosta histereza: "widziany
niedawno (w poblizu tego samego miejsca) = wciaz pokazuj". Jesli w danym
miejscu pojawi sie fresh klaster ZNACZACO inny (poza progiem dopasowania -
np. obiekt faktycznie zniknal i cos calkiem innego sie pojawilo, albo
przesuniecie jest zbyt duze), NIE jest dopasowywany do starego - stary
naturalnie wygasa po timeout_s, nowy zaczyna wlasna historie od zera. To
realizuje "chyba ze cos diametralnie sie zmieni" bez dodatkowej logiki -
sama zasada dopasowania po odleglosci to zapewnia.

Prog dopasowania jest RANGE-ADAPTIVE (rosnie z odlegloscia od czujnika) -
ta sama fizyczna przeslanka co w obstacle_clustering.py (gestosc/precyzja
Unitree L1 maleje z odlegloscia, wiec ta sama bezwzgledna tolerancja
pozycji jest za ciasna daleko i niepotrzebnie luzna blisko).
"""

import time
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from .obstacle_clustering import ObstacleCluster

DEFAULT_MATCH_BASE_M = 0.15
DEFAULT_MATCH_SLOPE = 0.03
DEFAULT_MATCH_MAX_M = 0.6
DEFAULT_PERSISTENCE_TIMEOUT_S = 4.0


@dataclass
class _TrackedCluster:
    cluster: ObstacleCluster
    last_seen: float


def _match_threshold(range_a: float, range_b: float, base_m: float, slope: float, max_m: float) -> float:
    avg_range = (range_a + range_b) / 2.0
    return min(base_m + slope * avg_range, max_m)


class ClusterPersistenceTracker:
    def __init__(
        self,
        match_base_m: float = DEFAULT_MATCH_BASE_M,
        match_slope: float = DEFAULT_MATCH_SLOPE,
        match_max_m: float = DEFAULT_MATCH_MAX_M,
        timeout_s: float = DEFAULT_PERSISTENCE_TIMEOUT_S,
    ):
        self.match_base_m = match_base_m
        self.match_slope = match_slope
        self.match_max_m = match_max_m
        self.timeout_s = timeout_s
        self._tracked: List[_TrackedCluster] = []

    def update(self, fresh_clusters: List[ObstacleCluster], now: Optional[float] = None) -> List[ObstacleCluster]:
        """
        fresh_clusters: wynik biezacego ticku cluster_obstacles() (bez
        pamieci o przeszlosci).

        Zwraca pelna liste widocznych klastrow: fresh dopasowane do
        istniejacych + fresh niedopasowane (nowe) + stare NIEPOTWIERDZONE
        w tym ticku, ale wciaz w oknie timeout_s (dzieki temu nie znikaja
        natychmiast po jednym pominietym ticku).
        """
        now = now if now is not None else time.monotonic()

        matched_tracked_idx = set()
        matched_fresh_idx = set()

        # Dopasowanie zachlanne: kazdy fresh klaster szuka najblizszego
        # NIEDOPASOWANEGO JESZCZE sledzonego klastra, w progu zaleznym od
        # odleglosci pary od czujnika (patrz _match_threshold).
        for fi, fc in enumerate(fresh_clusters):
            fc_range = float(np.hypot(fc.centroid_x, fc.centroid_y))
            best_idx = None
            best_dist = None
            best_threshold = None
            for ti, tc in enumerate(self._tracked):
                if ti in matched_tracked_idx:
                    continue
                tc_range = float(np.hypot(tc.cluster.centroid_x, tc.cluster.centroid_y))
                threshold = _match_threshold(fc_range, tc_range, self.match_base_m, self.match_slope, self.match_max_m)
                dist = float(
                    np.hypot(fc.centroid_x - tc.cluster.centroid_x, fc.centroid_y - tc.cluster.centroid_y)
                )
                if dist < threshold and (best_dist is None or dist < best_dist):
                    best_dist = dist
                    best_idx = ti
                    best_threshold = threshold
            if best_idx is not None:
                self._tracked[best_idx] = _TrackedCluster(cluster=fc, last_seen=now)
                matched_tracked_idx.add(best_idx)
                matched_fresh_idx.add(fi)

        # Fresh klastry bez dopasowania - nowe obiekty, zaczynaja wlasna
        # histerezę od teraz.
        for fi, fc in enumerate(fresh_clusters):
            if fi not in matched_fresh_idx:
                self._tracked.append(_TrackedCluster(cluster=fc, last_seen=now))

        # Wygasniecie: sledzone klastry niepotwierdzone od >= timeout_s sa
        # usuwane. Te potwierdzone (lub wciaz w oknie tolerancji) zostaja -
        # to jest cala "trwalosc" o ktora chodzi.
        self._tracked = [t for t in self._tracked if (now - t.last_seen) <= self.timeout_s]

        return [t.cluster for t in self._tracked]

    def reset(self) -> None:
        self._tracked = []
