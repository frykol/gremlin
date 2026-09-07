"""
ROZDZIELCZOSC detekcji: jak blisko siebie moga stac dwa obiekty, zeby
potok wciaz zglosil je jako osobne przeszkody.

To jest miara "szczegolowosci" detekcji i jednoczesnie miejsce, gdzie
lacza sie dwa parametry z roznych modulow: wielkosc woksela w
LidarObstacleReducer (rozdzielczosc przestrzenna po deduplikacji) i prog
laczenia eps w cluster_obstacles (jak chetnie sasiednie punkty ida do
jednego klastra). Testujemy je RAZEM, bo osobno kazdy z nich mozna
"poprawic" tak, ze drugi i tak zetrze zysk.

Druga strona medalu: mniejszy eps grozi ROZPADANIEM sie dalekich obiektow
(gestosc zwrotow L1 mocno maleje z odlegloscia). Dlatego kazda zmiana
rozdzielczosci ma tu obok test integralnosci dalekiego, rzadkiego obiektu.
"""

import numpy as np

from backend.lidar.obstacle_clustering import cluster_obstacles
from src.hardware.lidar.obstacle_reducer import LidarObstacleReducer

# Zmierzona rozdzielczosc przed zmiana wynosila 0.35 m (woksel 8 cm,
# eps0 0.10). Ten prog blokuje ciche cofniecie sie do tamtego stanu.
REQUIRED_RESOLUTION_M = 0.25


def _tilt_to_raw(leveled: np.ndarray, reducer: LidarObstacleReducer) -> np.ndarray:
    """Odwraca korekte pochylenia - reduce() oczekuje ukladu CZUJNIKA."""
    return leveled @ reducer._tilt_matrix


def _scene_two_objects(separation_m: float, distance_m: float = 2.0, seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    reducer = LidarObstacleReducer()
    n_floor = 20000
    floor = np.column_stack([
        rng.uniform(-6, 6, n_floor),
        rng.uniform(-6, 6, n_floor),
        rng.normal(0, 0.01, n_floor),
    ])
    objects = [
        np.column_stack([
            rng.normal(cx, 0.03, 600),
            rng.normal(distance_m, 0.03, 600),
            rng.uniform(0.06, 0.30, 600),
        ])
        for cx in (-separation_m / 2, separation_m / 2)
    ]
    leveled = np.vstack([floor] + objects)
    return np.column_stack([
        _tilt_to_raw(leveled, reducer),
        rng.uniform(120, 200, len(leveled)),
    ]).astype(np.float32)


def _scene_far_sparse_object(distance_m: float, n_points: int, seed: int = 9) -> np.ndarray:
    rng = np.random.default_rng(seed)
    reducer = LidarObstacleReducer()
    n_floor = 20000
    floor = np.column_stack([
        rng.uniform(-8, 8, n_floor),
        rng.uniform(-8, 8, n_floor),
        rng.normal(0, 0.012, n_floor),
    ])
    obj = np.column_stack([
        rng.normal(0, 0.10, n_points),
        rng.normal(distance_m, 0.10, n_points),
        rng.uniform(0.06, 0.5, n_points),
    ])
    leveled = np.vstack([floor, obj])
    return np.column_stack([
        _tilt_to_raw(leveled, reducer),
        rng.uniform(120, 200, len(leveled)),
    ]).astype(np.float32)


def _detect(raw: np.ndarray):
    reducer = LidarObstacleReducer()
    reducer.calibrate_ground(raw)
    return cluster_obstacles(reducer.reduce(raw))


def test_resolves_two_objects_at_required_separation():
    raw = _scene_two_objects(REQUIRED_RESOLUTION_M, distance_m=2.0)

    clusters = _detect(raw)

    near = [c for c in clusters if abs(c.centroid_y - 2.0) < 0.4]
    assert len(near) >= 2, (
        f"dwa obiekty oddalone o {REQUIRED_RESOLUTION_M} m zlaly sie "
        f"w {len(near)} klaster(ow)"
    )


def test_resolves_clearly_separated_objects():
    raw = _scene_two_objects(0.5, distance_m=2.0)

    clusters = _detect(raw)

    near = [c for c in clusters if abs(c.centroid_y - 2.0) < 0.5]
    assert len(near) >= 2


def test_far_sparse_object_stays_whole_despite_finer_threshold():
    # Cena za wieksza rozdzielczosc bylaby zbyt wysoka, gdyby dalekie
    # obiekty zaczely sie rozpadac - tu tego pilnujemy.
    for distance_m, n_points in ((6.5, 120), (7.5, 80), (7.5, 50)):
        raw = _scene_far_sparse_object(distance_m, n_points)

        clusters = _detect(raw)

        at_range = [c for c in clusters if abs(c.centroid_y - distance_m) < 0.9]
        assert len(at_range) == 1, (
            f"obiekt na {distance_m} m ({n_points} pkt) dal "
            f"{len(at_range)} klastrow zamiast 1"
        )


def _scene_rich_room(seed: int = 5) -> np.ndarray:
    """Realistyczna scena: 91% podlogi (tyle zmierzono na zywych danych),
    sciana i kilka obiektow w roznych odlegloscach."""
    rng = np.random.default_rng(seed)
    reducer = LidarObstacleReducer()
    n = 30000
    n_floor = int(n * 0.91)
    floor = np.column_stack([
        rng.uniform(-6, 6, n_floor),
        rng.uniform(-6, 6, n_floor),
        rng.normal(0, 0.012, n_floor),
    ])
    n_wall = int(n * 0.05)
    wall = np.column_stack([
        rng.uniform(-5, 5, n_wall),
        np.full(n_wall, 5.5) + rng.normal(0, 0.02, n_wall),
        rng.uniform(0.05, 1.1, n_wall),
    ])
    n_obj = (n - n_floor - n_wall) // 6
    objects = [
        np.column_stack([
            rng.normal(cx, 0.05, n_obj),
            rng.normal(cy, 0.05, n_obj),
            rng.uniform(0.06, 0.4, n_obj),
        ])
        for cx, cy in [(1, 2), (-1.5, 1.2), (2.5, 3), (0.3, 4), (-2, 3.5), (1.8, 6.0)]
    ]
    leveled = np.vstack([floor, wall] + objects)
    return np.column_stack([
        _tilt_to_raw(leveled, reducer),
        rng.uniform(120, 200, len(leveled)),
    ]).astype(np.float32)


def test_voxel_grid_is_not_the_detail_bottleneck_on_a_rich_scene():
    # Woksel byl wezszym gardlem niz limit punktow: przy 8 cm przez potok
    # przechodzilo ~1400 punktow NIEZALEZNIE od budzetu (zmierzone: limity
    # 1500 i 5000 dawaly tyle samo), wiec podnoszenie samego
    # max_output_points nic nie dawalo.
    raw = _scene_rich_room()
    reducer = LidarObstacleReducer()
    reducer.calibrate_ground(raw)

    reduced = reducer.reduce(raw)

    assert reduced.shape[0] > 2000, (
        f"potok przepuszcza tylko {reduced.shape[0]} punktow - za malo na detale"
    )
    # I to woksel, a nie sufit, decyduje - wynik nie jest przyciety do limitu.
    assert reduced.shape[0] < reducer.max_output_points, (
        "wynik obciety limitem max_output_points - limit znowu jest wezszym gardlem"
    )


def test_all_objects_in_a_rich_scene_are_detected():
    raw = _scene_rich_room()

    clusters = _detect(raw)

    for cx, cy in [(1, 2), (-1.5, 1.2), (2.5, 3), (0.3, 4), (-2, 3.5), (1.8, 6.0)]:
        assert any(
            abs(c.centroid_x - cx) < 0.35 and abs(c.centroid_y - cy) < 0.35
            for c in clusters
        ), f"nie wykryto obiektu w ({cx}, {cy})"
