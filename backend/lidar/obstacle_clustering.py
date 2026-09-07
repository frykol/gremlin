"""
Klastrowanie zredukowanej chmury punktow-przeszkod (juz po ground removal
i wokselizacji z LidarObstacleReducer) w dyskretne obiekty do wizualizacji
(nakladka 3D + radar 2D), a nie surowa chmure kropek.

Metoda: RANGE-ADAPTIVE Euclidean clustering (KD-tree + adaptacyjny prog
odleglosci rosnacy z zasiegiem). Poprzednia metoda (siatka 8cm + connected
components) uzywala STALEJ tolerancji polaczenia niezaleznie od odleglosci
od czujnika, co jest niedopasowane do fizyki Unitree L1: gestosc zwrotow
mocno maleje z odlegloscia (te same 120 pkt/skan rozklada sie na wiekszy
luk), wiec:
- zbyt mala stala tolerancja -> dalekie obiekty rozpadaja sie na wiele
  drobnych fragmentow (za rzadkie, zeby "dotykac" sie w stalej siatce),
- zbyt duza stala tolerancja -> bliskie, gesto upakowane obiekty sklejaja
  sie ze soba.
Adaptacyjny prog (eps rosnie z odlegloscia od czujnika) rozwiazuje oba
problemy jednoczesnie, bez potrzeby modelu ML/danych treningowych - patrz
dyskusja w rozmowie (research pokazal to jako najsilniejszego kandydata
obok prostego gridu).
"""

from dataclasses import dataclass
from typing import List

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

# Progi laczenia dobrane pomiarowo pod ROZDZIELCZOSC detekcji (patrz
# tests/test_detection_resolution.py). Poprzednie wartosci (0.10/0.03/0.40)
# dawaly rozdzielczosc 0.35m na dystansie 2m - dwa obiekty blizej siebie
# zlewaly sie w jedna przeszkode. Obecne daja 0.25m, przy zachowanej
# integralnosci dalekich, rzadkich obiektow (sprawdzone do 7.5m i zaledwie
# 50 punktow - wciaz jeden caly klaster, nie rozsypany).
DEFAULT_EPS0_M = 0.05
DEFAULT_EPS_SLOPE = 0.02
DEFAULT_MAX_EPS_M = 0.22
DEFAULT_MAX_CLUSTER_DIAMETER_M = 1.5
# Probny podzial zbyt duzego klastra rozroznia dwa przypadki, ktore
# wczesniej byly traktowane identycznie:
# - CHAINING (realne obiekty zlaczone rzadkim mostkiem): zawezenie progu
#   odcina mostek, a realne obiekty zostaja - podzial jest sluszny;
# - JEDEN DUZY, CIAGLY obiekt (sciana, kanapa, blat): zawezenie progu
#   schodzi ponizej realnego odstepu miedzy punktami, wiec obiekt
#   rozsypuje sie na drobiny, a te ponizej min_points sa wyrzucane -
#   zmierzone: sciana 5m/600pkt przezywala w 55%, a sciana 4m byla
#   raportowana jako przeszkoda o szerokosci 0.63m zamiast 4m.
#
# Uwaga: sama retencja punktow NIE rozroznia obu przypadkow (zmierzone:
# sciana 4m 0.827, chaining 0.821 - praktycznie tyle samo). Rozstrzyga
# dopiero STRUKTURA wyniku probnego podzialu, patrz _min_pairwise_gap i
# _combined_extent.
#
# Ile najwyzej (jako ulamek pierwotnej srednicy) moga lacznie zajmowac
# czesci po podziale, zeby uznac, ze klaster faktycznie sie ZWEZIL (odpadl
# rzadki mostek/ogon), a nie tylko rozkruszyl. Zmierzone: przy chainingu
# rdzen po odcieciu mostka mial 0.30m z pierwotnych 3.49m (~0.09), przy
# scianie czesci wciaz pokrywaly praktycznie cala jej dlugosc (~1.0).
SPLIT_COMPACTION_RATIO = 0.5
# Zmierzone empirycznie (patrz brainstorming w rozmowie): mimo kalibracji
# plaszczyzny podlogi/stolu, ~13% punktow blisko robota nadal przekracza
# margines wysokosci - blisko-zasiegowy szum pomiarowy, nie realne
# przeszkody. min_points=8 (poprzedni prog) nadal przepuszczal duzo
# granicznych klastrow (8-19 pkt) - na zywych danych (813 obserwacji, 24
# tickow obstacle_loop) mediana wielkosci klastra to 20 punktow, a duzy
# skok obserwacji dokladnie na starej granicy (8) sugerowal, ze wiele z
# nich to wciaz szum ledwo przekraczajacy prog. Podniesienie do 20 (mediana)
# odcina dokladnie te "podejrzana" dolna polowe (srednio ~34 -> ~17
# klastrow/tick), zachowujac wszystkie znaczace wykrycia (dziesiatki-setki
# punktow).
DEFAULT_MIN_POINTS = 20
# Skala intensywnosci L1 to 0-255 (patrz obstacle_reducer.py min_intensity).
# Dwa punkty przestrzennie blisko siebie, ale o intensywnosci roznej o
# wiecej niz ten prog, NIE sa laczone w jeden klaster - prawdopodobnie
# rozne materialy/powierzchnie (np. krawedz mebla na tle sciany), nie
# jeden fizyczny obiekt.
DEFAULT_MAX_INTENSITY_DIFF = 60.0


@dataclass
class ObstacleCluster:
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float
    centroid_x: float
    centroid_y: float
    centroid_z: float
    point_count: int
    mean_intensity: float
    intensity_std: float
    # Wypelniane PO klastrowaniu (patrz backend/lidar/anomaly_scorer.py) -
    # 0.5 = "brak oceny" (model jeszcze nie gotowy / nie uzyto scorera).
    anomaly_score: float = 0.5


def _segment_oversized(
    cluster_pts: np.ndarray, max_diameter_m: float, min_points: int
) -> List["ObstacleCluster"]:
    """
    Tnie JEDEN duzy, prawdziwy obiekt (sciana, kanapa, blat) na kafelki w
    XY, tak by kazdy zwracany bounding box mial przekatna <= max_diameter_m.

    Po co, skoro obiekt jest prawdziwy: prostokat otaczajacy dluga, ukosna
    strukture obejmuje w wiekszosci PUSTA przestrzen i raportuje ja jako
    przeszkode. Zmierzone na zywych danych: najwieksze boxy mialy 5.7-8.4 m2
    przy gestosci 75 pkt/m2 wobec mediany 160 - polowa takiego boxa to
    powietrze. Kafelkowanie daje ten sam zasieg detekcji przy ciasnych
    boxach.

    min_points STOSUJEMY tu tak samo jak wszedzie indziej w klastrowaniu -
    regresja odkryta na zywych danych: zalozenie "punkty naleza do klastra,
    ktory juz przeszedl prog jako calosc" bylo blednie ekstrapolowane na
    POSZCZEGOLNE kafelki. Rozlegla, RZADKA plama szumu (np. resztki
    ground-removal na dystansie) moze przekroczyc max_cluster_diameter_m
    jako calosc, mimo ze zaden jej fragment nie jest gesty - pocieta na
    kafelki taka plama dawala dziesiatki "przeszkod" po 1-19 punktow.
    Zmierzone: 47% wszystkich klastrow w typowej scenie mialo mniej niz
    min_points, wylacznie za sprawa tej funkcji (zwykle klastrowanie NIGDY
    nie zwraca czegos ponizej progu) - to byly wlasnie fantomowe boxy w
    pustej przestrzeni z ekranu uzytkownika.
    """
    # Bok kafelka tak dobrany, zeby PRZEKATNA kafelka nie przekroczyla
    # limitu (kwadrat o boku s ma przekatna s*sqrt(2)).
    tile = max(max_diameter_m / np.sqrt(2.0), 1e-3)

    xy = cluster_pts[:, :2]
    tile_idx = np.floor(xy / tile).astype(np.int64)
    _, inverse = np.unique(tile_idx, axis=0, return_inverse=True)
    inverse = np.asarray(inverse).reshape(-1)

    out: List[ObstacleCluster] = []
    for tile_id in range(int(inverse.max()) + 1):
        mask = inverse == tile_id
        count = int(mask.sum())
        if count < min_points:
            continue
        out.append(_make_cluster(cluster_pts[mask], count))
    return out


def _combined_extent(clusters: List[ObstacleCluster]) -> float:
    """Srednica wspolnego bounding boxa wszystkich klastrow (w XY)."""
    if not clusters:
        return 0.0
    x_min = min(c.x_min for c in clusters)
    x_max = max(c.x_max for c in clusters)
    y_min = min(c.y_min for c in clusters)
    y_max = max(c.y_max for c in clusters)
    return float(np.hypot(x_max - x_min, y_max - y_min))


def _min_pairwise_gap(clusters: List[ObstacleCluster]) -> float:
    """
    Najmniejsza przerwa (w XY) miedzy bounding boxami dowolnej pary
    klastrow; 0.0 gdy ktorakolwiek para sie styka/przenika.

    To jest sygnal rozstrzygajacy, czy probny podzial duzego klastra byl
    prawdziwym ROZDZIELENIEM, czy tylko ROZKRUSZENIEM jednego obiektu.
    Zmierzone: sciana 3-5m rozpadala sie na czesci odlegle o 0.017-0.027m
    (czyli stykajace sie - to artefakty zawezonego progu), a dwa realne
    obiekty polaczone rzadkim mostkiem rozdzielaly sie na czesci odlegle o
    3.825m. Roznica dwoch rzedow wielkosci.
    """
    if len(clusters) < 2:
        return 0.0
    gap = float("inf")
    for i in range(len(clusters)):
        a = clusters[i]
        for j in range(i + 1, len(clusters)):
            b = clusters[j]
            dx = max(0.0, max(a.x_min, b.x_min) - min(a.x_max, b.x_max))
            dy = max(0.0, max(a.y_min, b.y_min) - min(a.y_max, b.y_max))
            gap = min(gap, float(np.hypot(dx, dy)))
            if gap == 0.0:
                return 0.0
    return gap


def _adaptive_threshold(range_i: np.ndarray, range_j: np.ndarray, eps0: float, slope: float) -> np.ndarray:
    """Prog polaczenia dla pary punktow - rosnie liniowo ze SREDNIM
    zasiegiem pary od czujnika (odleglosc XY od (0,0), gdzie stoi robot)."""
    avg_range = (range_i + range_j) / 2.0
    return eps0 + slope * avg_range


def _cluster_indices(
    points_xy: np.ndarray,
    intensity: np.ndarray,
    eps0: float,
    slope: float,
    max_eps: float,
    max_intensity_diff: float,
) -> np.ndarray:
    """Zwraca etykiety (int, 0-indexed) grupujace punkty metoda
    range-adaptive Euclidean clustering + kryterium podobienstwa
    intensywnosci. -1 nie wystepuje - kazdy punkt nalezy do jakiegos
    komponentu (nawet jesli to komponent 1-elementowy)."""
    n = points_xy.shape[0]
    if n == 0:
        return np.empty(0, dtype=np.int64)
    if n == 1:
        return np.zeros(1, dtype=np.int64)

    tree = cKDTree(points_xy)
    # Kandydaci na krawedzie: wszystkie pary w promieniu max_eps (gorny
    # sufit adaptacyjnego progu) - potem odsiewamy do faktycznego progu
    # zaleznego od odleglosci kazdej pary od czujnika ORAZ do podobienstwa
    # intensywnosci (rozne materialy nie laczymy, nawet gdy sa blisko).
    pairs = tree.query_pairs(max_eps, output_type="ndarray")

    if pairs.shape[0] == 0:
        # Brak jakichkolwiek par w zasiegu - kazdy punkt to osobny komponent.
        return np.arange(n, dtype=np.int64)

    range_from_sensor = np.linalg.norm(points_xy, axis=1)
    i_idx, j_idx = pairs[:, 0], pairs[:, 1]
    actual_dist = np.linalg.norm(points_xy[i_idx] - points_xy[j_idx], axis=1)
    threshold = _adaptive_threshold(range_from_sensor[i_idx], range_from_sensor[j_idx], eps0, slope)
    spatial_valid = actual_dist <= threshold

    intensity_diff = np.abs(intensity[i_idx] - intensity[j_idx])
    intensity_valid = intensity_diff <= max_intensity_diff

    valid = spatial_valid & intensity_valid

    i_valid = i_idx[valid]
    j_valid = j_idx[valid]

    graph = coo_matrix(
        (np.ones(i_valid.shape[0], dtype=bool), (i_valid, j_valid)),
        shape=(n, n),
    )
    _, labels = connected_components(graph, directed=False)
    return labels


def cluster_obstacles(
    points: np.ndarray,
    eps0_m: float = DEFAULT_EPS0_M,
    eps_slope: float = DEFAULT_EPS_SLOPE,
    max_eps_m: float = DEFAULT_MAX_EPS_M,
    min_points: int = DEFAULT_MIN_POINTS,
    max_cluster_diameter_m: float = DEFAULT_MAX_CLUSTER_DIAMETER_M,
    max_intensity_diff: float = DEFAULT_MAX_INTENSITY_DIFF,
) -> List[ObstacleCluster]:
    """
    points: (N,4) w poziomym ukladzie robota (x=prawo, y=przod,
    z=wysokosc, intensity) - wynik LidarObstacleReducer.reduce().

    eps0_m: bazowy prog polaczenia (przy zasiegu ~0m od czujnika).
    eps_slope: jak szybko prog rosnie z odlegloscia od czujnika (m progu
    na m zasiegu) - kompensuje malejaca gestosc chmury L1 z odlegloscia.
    max_eps_m: gorny sufit progu (nawet bardzo daleko nie rosnie w
    nieskonczonosc) - ogranicza tez koszt KD-tree query_pairs.
    min_points: klastry mniejsze sa odrzucane jako szum.
    max_cluster_diameter_m: nawet adaptacyjny prog moze w rzadkich
    przypadkach polaczyc lancuch punktow w zbyt duzy klaster (patrz
    obstacle_clustering historii zmian) - klastry przekraczajace ten limit
    sa rekurencyjnie przeklastrowywane z zawezonym eps0/max_eps.
    max_intensity_diff: dwa punkty blisko przestrzennie, ale o intensywnosci
    roznej o wiecej niz to - NIE laczone (rozne materialy/powierzchnie).
    """
    if points.shape[0] == 0:
        return []

    clusters: List[ObstacleCluster] = []
    _cluster_recursive(
        points,
        eps0_m,
        eps_slope,
        max_eps_m,
        min_points,
        max_cluster_diameter_m,
        max_intensity_diff,
        clusters,
    )
    return clusters


def _cluster_recursive(
    points: np.ndarray,
    eps0_m: float,
    eps_slope: float,
    max_eps_m: float,
    min_points: int,
    max_cluster_diameter_m: float,
    max_intensity_diff: float,
    out: List[ObstacleCluster],
) -> None:
    labels = _cluster_indices(points[:, :2], points[:, 3], eps0_m, eps_slope, max_eps_m, max_intensity_diff)
    num_labels = int(labels.max()) + 1 if labels.size else 0

    for label_id in range(num_labels):
        mask = labels == label_id
        count = int(mask.sum())
        if count < min_points:
            continue
        cluster_pts = points[mask]

        x_span = cluster_pts[:, 0].max() - cluster_pts[:, 0].min()
        y_span = cluster_pts[:, 1].max() - cluster_pts[:, 1].min()
        diameter = float(np.hypot(x_span, y_span))

        # Podloga rekurencji: ponizej ~2cm prog jest juz blisko szumu
        # pomiarowego sensora - dalsze zawezanie tylko rozdrobniloby
        # PRAWDZIWY duzy obiekt (np. sciane) na nic, zamiast poprawnie
        # rozbic sztuczny lancuch. Taki klaster jest wtedy akceptowany
        # jako jeden, faktycznie duzy obiekt.
        if diameter > max_cluster_diameter_m and eps0_m > 0.02:
            # Podejrzenie chainingu - sprobuj przeklastrowac TYLKO te punkty
            # z ciasniejszym progiem. Wynik ladujemy najpierw do listy
            # PROBNEJ: sam fakt, ze klaster jest duzy, nie dowodzi jeszcze
            # chainingu, a slepe dzielenie niszczylo prawdziwe duze obiekty
            # (patrz komentarz przy SPLIT_COMPACTION_RATIO).
            candidate: List[ObstacleCluster] = []
            _cluster_recursive(
                cluster_pts,
                eps0_m * 0.5,
                eps_slope * 0.5,
                max_eps_m * 0.5,
                min_points,
                max_cluster_diameter_m,
                max_intensity_diff,
                candidate,
            )
            # Podzial przyjmujemy tylko, gdy faktycznie COS OSIAGNAL -
            # czyli gdy zachodzi jedno z dwojga:
            #
            # (a) ROZDZIELENIE: czesci sa od siebie dalej, niz klastrowanie
            #     na tym poziomie w ogole potrafiloby je polaczyc
            #     (max_eps_m) - to prawdziwe, osobne obiekty;
            # (b) ZWEZENIE: czesci lacznie zajmuja duzo mniejszy obszar niz
            #     oryginal - z klastra odpadl rzadki "ogon" (mostek), a
            #     zostal zwarty rdzen.
            #
            # Odrzucamy dokladnie przypadek posredni: czesci wciaz pokrywaja
            # ten sam obszar co oryginal i stykaja sie ze soba. To nie jest
            # podzial, tylko ROZKRUSZENIE jednego duzego obiektu (sciana,
            # kanapa, blat) przez zbyt ciasny prog.
            combined_extent = _combined_extent(candidate)
            separated = _min_pairwise_gap(candidate) > max_eps_m
            compacted = combined_extent < SPLIT_COMPACTION_RATIO * diameter
            clean_split = bool(candidate) and (separated or compacted)
            if clean_split:
                # Realne rozdzielenie - mostek odpadl, obiekty zostaly.
                out.extend(candidate)
                continue
            # Podzial rozsypal obiekt zamiast go rozdzielic - to byl JEDEN
            # duzy obiekt, nie lancuch. Nie gubimy go i nie zwracamy jako
            # jednego gigantycznego prostokata (ktory obejmowalby glownie
            # pusta przestrzen) - tniemy go na ciasne kafelki.
            out.extend(_segment_oversized(cluster_pts, max_cluster_diameter_m, min_points))
            continue

        if diameter > max_cluster_diameter_m:
            # Ta sama zasada na dnie rekurencji (eps0_m juz za maly, zeby
            # probowac dzielic): duzy obiekt raportujemy kafelkami, nie
            # jednym boxem obejmujacym powietrze.
            out.extend(_segment_oversized(cluster_pts, max_cluster_diameter_m, min_points))
            continue

        out.append(_make_cluster(cluster_pts, count))


def _make_cluster(cluster_pts: np.ndarray, count: int) -> ObstacleCluster:
    return ObstacleCluster(
        x_min=float(cluster_pts[:, 0].min()),
        x_max=float(cluster_pts[:, 0].max()),
        y_min=float(cluster_pts[:, 1].min()),
        y_max=float(cluster_pts[:, 1].max()),
        z_min=float(cluster_pts[:, 2].min()),
        z_max=float(cluster_pts[:, 2].max()),
        centroid_x=float(cluster_pts[:, 0].mean()),
        centroid_y=float(cluster_pts[:, 1].mean()),
        centroid_z=float(cluster_pts[:, 2].mean()),
        point_count=count,
        mean_intensity=float(cluster_pts[:, 3].mean()),
        intensity_std=float(cluster_pts[:, 3].std()),
    )
