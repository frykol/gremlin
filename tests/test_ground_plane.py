import numpy as np

from src.hardware.lidar.ground_plane import fit_ground_plane


def test_too_few_points_returns_none():
    points = np.random.randn(10, 3)
    assert fit_ground_plane(points) is None


def test_fits_flat_horizontal_plane():
    rng = np.random.default_rng(42)
    n = 500
    xy = rng.uniform(-3, 3, size=(n, 2))
    z = np.full(n, 0.5) + rng.normal(0, 0.005, size=n)  # plaska plaszczyzna Z=0.5 + szum
    points = np.column_stack([xy, z])

    result = fit_ground_plane(points, rng=np.random.default_rng(1))
    assert result is not None
    normal, point_on_plane = result

    # Normal plaszczyzny poziomej powinien byc (0,0,1) lub (0,0,-1).
    assert abs(abs(normal[2]) - 1.0) < 0.02
    assert abs(point_on_plane[2] - 0.5) < 0.02


def test_fits_tilted_plane_and_computes_correct_signed_distance():
    rng = np.random.default_rng(7)
    n = 800
    xy = rng.uniform(-3, 3, size=(n, 2))
    # Plaszczyzna nachylona: z = 0.1*x + 0.05*y + 0.3
    z = 0.1 * xy[:, 0] + 0.05 * xy[:, 1] + 0.3 + rng.normal(0, 0.005, size=n)
    plane_points = np.column_stack([xy, z])

    # Dodaj kilka punktow WYRAZNIE nad plaszczyzna (symulacja przeszkody).
    obstacle = np.array([[0.0, 0.0, 1.5], [0.1, 0.1, 1.6], [-0.1, 0.2, 1.4]])
    points = np.vstack([plane_points, obstacle])

    result = fit_ground_plane(points, rng=np.random.default_rng(2))
    assert result is not None
    normal, point_on_plane = result

    # Odleglosc podlogowych punktow od dopasowanej plaszczyzny ~0.
    plane_dist = np.abs((plane_points - point_on_plane) @ normal)
    assert plane_dist.mean() < 0.02

    # Odleglosc przeszkody powinna byc duza (rzedu >1m).
    obstacle_dist = (obstacle - point_on_plane) @ normal
    assert np.all(np.abs(obstacle_dist) > 1.0)


def test_no_dominant_plane_in_random_noise_returns_none():
    rng = np.random.default_rng(3)
    points = rng.uniform(-2, 2, size=(300, 3))  # rownomierny szum 3D, brak plaszczyzny
    result = fit_ground_plane(points, rng=np.random.default_rng(4), min_inlier_ratio=0.3)
    assert result is None


def _wall_dominated_scene(n_wall=2000, n_floor=800, seed=0):
    """Robot blisko duzej sciany: SCIANA (plaszczyzna pionowa y=2.0) ma
    wiecej punktow niz podloga - czysto "dominujacy" RANSAC wybralby ja."""
    rng = np.random.default_rng(seed)
    wall = np.column_stack([
        rng.uniform(-2, 2, n_wall),
        np.full(n_wall, 2.0) + rng.normal(0, 0.005, n_wall),
        rng.uniform(0, 1.5, n_wall),
    ])
    floor = np.column_stack([
        rng.uniform(-2, 2, n_floor),
        rng.uniform(0, 2, n_floor),
        np.full(n_floor, -0.05) + rng.normal(0, 0.005, n_floor),
    ])
    return np.vstack([wall, floor]), wall, floor


def test_rejects_vertical_wall_even_when_it_dominates_the_scene():
    # Bez ograniczenia pionowosci normalnej RANSAC dopasowuje SCIANE (bo ma
    # najwiecej punktow), co w obstacle_reducer.reduce() odwraca cala
    # detekcje: sciana znika jako "podloga", a podloga staje sie
    # "przeszkoda". Plaszczyzna PODLOGI z definicji jest ~pozioma, wiec
    # dopasowanie o normalnej odchylonej od pionu jest odrzucane.
    points, _, _ = _wall_dominated_scene()

    result = fit_ground_plane(points, rng=np.random.default_rng(1))

    if result is not None:
        normal, _ = result
        # Cokolwiek zwrocone MUSI byc ~pozioma plaszczyzna, nigdy sciana.
        assert abs(normal[2]) > 0.8, f"dopasowano niepozioma plaszczyzne: {normal}"


def test_finds_horizontal_floor_under_dominant_wall_when_floor_is_large_enough():
    # Ta sama scena, ale podloga ma dosc punktow, zeby przejsc
    # min_inlier_ratio - filtr pionowosci powinien poprowadzic RANSAC do
    # PODLOGI, mimo ze sciana wciaz ma ich wiecej.
    points, _, floor = _wall_dominated_scene(n_wall=2000, n_floor=1200)

    result = fit_ground_plane(
        points, rng=np.random.default_rng(1), min_inlier_ratio=0.3
    )

    assert result is not None
    normal, point_on_plane = result
    assert abs(normal[2]) > 0.99  # pozioma
    # I faktycznie lezy na wysokosci podlogi (z=-0.05), nie sciany.
    assert abs(point_on_plane[2] - (-0.05)) < 0.02
    floor_dist = np.abs((floor - point_on_plane) @ normal)
    assert floor_dist.mean() < 0.02


def test_tilt_guard_can_be_disabled_explicitly():
    # Wylaczenie filtra (None) przywraca stare zachowanie "dowolna
    # dominujaca plaszczyzna" - do zastosowan innych niz podloga.
    points, _, _ = _wall_dominated_scene()

    result = fit_ground_plane(
        points, rng=np.random.default_rng(1), max_normal_tilt_deg=None
    )

    assert result is not None
    normal, _ = result
    assert abs(normal[2]) < 0.2  # bez filtra: dopasowano sciane
