import numpy as np
import pytest

from backend.lidar.obstacle_clustering import (
    DEFAULT_MAX_CLUSTER_DIAMETER_M,
    cluster_obstacles,
)


def _with_intensity(xyz: np.ndarray, value: float = 100.0) -> np.ndarray:
    """Dokleja stala kolumne intensywnosci - dla testow, ktorym nie zalezy
    na kryterium podobienstwa intensywnosci (ta sama wartosc wszedzie nigdy
    nie przekracza max_intensity_diff, wiec nie wplywa na wynik)."""
    xyz = np.asarray(xyz, dtype=np.float32)
    intensity = np.full((xyz.shape[0], 1), value, dtype=np.float32)
    return np.hstack([xyz, intensity])


def test_empty_input_returns_no_clusters():
    assert cluster_obstacles(np.empty((0, 4))) == []


def test_two_far_apart_groups_become_two_clusters():
    group_a = np.array([[0.0, 0.0, 0.1], [0.05, 0.0, 0.1], [0.0, 0.05, 0.1]])
    group_b = np.array([[3.0, 3.0, 0.2], [3.05, 3.0, 0.2], [3.0, 3.05, 0.2]])
    points = _with_intensity(np.vstack([group_a, group_b]))

    clusters = cluster_obstacles(points, min_points=1)

    assert len(clusters) == 2
    counts = sorted(c.point_count for c in clusters)
    assert counts == [3, 3]


def test_small_gap_still_joins_into_one_cluster():
    # Punkty oddalone o 16cm - z wystarczajaco duzym progiem eps0 powinny
    # polaczyc sie w jeden klaster.
    points = _with_intensity(
        np.array(
            [
                [0.0, 0.0, 0.1],
                [0.16, 0.0, 0.1],
            ]
        )
    )

    clusters = cluster_obstacles(points, min_points=1, eps0_m=0.2)

    assert len(clusters) == 1
    assert clusters[0].point_count == 2


def test_gap_beyond_threshold_stays_separate():
    # Te same punkty (16cm), ale z za malym progiem - NIE powinny sie
    # polaczyc.
    points = _with_intensity(
        np.array(
            [
                [0.0, 0.0, 0.1],
                [0.16, 0.0, 0.1],
            ]
        )
    )

    clusters = cluster_obstacles(points, min_points=1, eps0_m=0.05, eps_slope=0.0)

    assert len(clusters) == 2


def test_threshold_grows_with_distance_from_sensor():
    # Ta sama 16cm przerwa, ale przy duzym zasiegu (10m) - eps_slope
    # powinien ja pokryc, mimo ze eps0 sam w sobie jest za maly.
    points = _with_intensity(
        np.array(
            [
                [10.0, 0.0, 0.1],
                [10.16, 0.0, 0.1],
            ]
        )
    )

    clusters = cluster_obstacles(points, min_points=1, eps0_m=0.05, eps_slope=0.02)
    # prog = 0.05 + 0.02*10.08 ~ 0.25m > 0.16m przerwy -> powinny sie polaczyc
    assert len(clusters) == 1


def test_cluster_below_min_points_is_dropped_as_noise():
    points = _with_intensity(np.array([[5.0, 5.0, 0.1], [5.0, 5.0, 0.1]]))

    clusters = cluster_obstacles(points, min_points=3)

    assert clusters == []


def test_sparse_bridge_does_not_chain_two_real_objects_into_one():
    # Regresja: dwa geste, odrebne obiekty (prawdziwe klastry) daleko od
    # siebie, polaczone RZADKIM lancuchem punktow-mostkow (kazdy sasiad w
    # zasiegu dylatacji gap_cells) - bez ochrony max_cluster_diameter_m
    # scipy.ndimage.label lacza to w JEDEN gigantyczny, fizycznie
    # bezsensowny klaster (potwierdzone empirycznie - patrz brainstorming).
    rng = np.random.default_rng(0)
    cluster_a = rng.normal([0.0, 0.0, 0.3], 0.05, size=(80, 3))
    cluster_b = rng.normal([4.0, 0.0, 0.3], 0.05, size=(80, 3))
    bridge_x = np.arange(0.3, 3.8, 0.12)
    bridge = np.column_stack(
        [bridge_x, np.zeros_like(bridge_x), np.full_like(bridge_x, 0.3)]
    )
    points = _with_intensity(np.vstack([cluster_a, cluster_b, bridge]).astype(np.float32))

    clusters = cluster_obstacles(points, min_points=3)

    assert len(clusters) == 2
    diameters = sorted(
        ((c.x_max - c.x_min) ** 2 + (c.y_max - c.y_min) ** 2) ** 0.5 for c in clusters
    )
    # Kazdy realny klaster ma srednice rzedu dziesiatkow cm, NIE metrow.
    assert all(d < 1.0 for d in diameters)


def _wall(length_m, n_points, distance_m=3.0, seed=0):
    """Dluga, ciagla, jednorodna sciana - jeden fizyczny obiekt."""
    rng = np.random.default_rng(seed)
    x = rng.uniform(-length_m / 2, length_m / 2, n_points)
    y = np.full(n_points, distance_m) + rng.normal(0, 0.01, n_points)
    z = rng.uniform(0.1, 0.8, n_points)
    return np.column_stack([x, y, z, np.full(n_points, 150.0)]).astype(np.float32)


def test_long_wall_is_not_shattered_and_its_points_are_not_lost():
    # Regresja: rekurencyjne dzielenie (max_cluster_diameter_m) polowilo eps
    # przy KAZDYM zbyt duzym klastrze, nie sprawdzajac, czy podzial ma sens.
    # Dla dlugiego, CIAGLEGO obiektu (sciana, kanapa, blat) prog schodzil
    # ponizej realnego odstepu miedzy punktami, wiec obiekt rozsypywal sie
    # na drobiny, a te ponizej min_points byly po cichu WYRZUCANE.
    # Zmierzone przed poprawka: sciana 5m/600pkt -> 10 fragmentow po ~0.25m,
    # pokrywajacych tylko 55% punktow. 45% sciany znikalo z wyniku.
    points = _wall(5.0, 600)

    clusters = cluster_obstacles(points)

    covered = sum(c.point_count for c in clusters)
    assert covered >= 0.9 * len(points), (
        f"zgubiono punkty sciany: {covered}/{len(points)}"
    )
    # UWAGA: nie stawiamy tu juz warunku na LICZBE klastrow. Pierwotnie ten
    # test wymagal <=3 ("sciana ma byc jednym obiektem"), ale takie
    # raportowanie dawalo jeden gigantyczny box obejmujacy glownie pusta
    # przestrzen. Duzy obiekt jest teraz celowo zwracany jako kilka
    # ciasnych kafelkow - patrz
    # test_large_object_is_reported_as_tight_segments_not_one_huge_box.
    # Wlasciwoscia pilnowana tutaj jest brak GUBIENIA punktow.


def test_medium_wall_stays_whole():
    points = _wall(3.0, 600)

    clusters = cluster_obstacles(points)

    covered = sum(c.point_count for c in clusters)
    assert covered >= 0.9 * len(points)


def test_wall_is_covered_end_to_end_by_its_clusters():
    # Sciana ma byc POKRYTA przez klastry na calej dlugosci - inaczej planer
    # omijania kolizji "zobaczy" mniejsza przeszkode niz jest naprawde.
    # Uwaga: NIE wymagamy, zeby byla JEDNYM boxem - patrz
    # test_large_object_is_reported_as_tight_segments_not_one_huge_box.
    points = _wall(4.0, 800)

    clusters = cluster_obstacles(points)

    covered_min = min(c.x_min for c in clusters)
    covered_max = max(c.x_max for c in clusters)
    assert covered_max - covered_min > 3.0, (
        f"klastry pokrywaja tylko {covered_max - covered_min:.2f}m z 4m sciany"
    )


def test_large_object_is_reported_as_tight_segments_not_one_huge_box():
    # Regresja w DRUGA strone: po naprawie rozdrabniania duze obiekty
    # zaczely byc jednym gigantycznym boxem. Zmierzone na zywych danych:
    # boxy 5.7-8.4 m2 przy gestosci 75 pkt/m2 wobec mediany 160 - czyli
    # prostokat otaczajacy dluga, ukosna strukture obejmowal w polowie
    # PUSTA przestrzen i raportowal ja jako przeszkode.
    #
    # Wymagamy obu rzeczy naraz: zaden pojedynczy box nie jest przesadnie
    # duzy, a punkty NIE gina.
    points = _wall(5.0, 600)

    clusters = cluster_obstacles(points)

    covered = sum(c.point_count for c in clusters)
    assert covered >= 0.9 * len(points), f"zgubiono punkty: {covered}/{len(points)}"

    for c in clusters:
        diameter = ((c.x_max - c.x_min) ** 2 + (c.y_max - c.y_min) ** 2) ** 0.5
        assert diameter <= DEFAULT_MAX_CLUSTER_DIAMETER_M + 1e-3, (
            f"klaster o srednicy {diameter:.2f}m przekracza limit"
        )


def test_segments_of_a_large_object_are_densely_filled():
    # Sedno zgloszenia "za duze przestrzenie": box ma opisywac obiekt, a nie
    # obszar wokol niego. Segmenty sciany musza byc gesto wypelnione.
    points = _wall(5.0, 600)

    clusters = cluster_obstacles(points)

    for c in clusters:
        area = max((c.x_max - c.x_min) * (c.y_max - c.y_min), 1e-6)
        assert c.point_count / area > 20, (
            f"rzadki box: {c.point_count} pkt na {area:.2f} m2"
        )


def test_very_different_intensity_prevents_merge_despite_proximity():
    # Dwa punkty blisko przestrzennie (2cm - w zasiegu domyslnego eps0),
    # ale o skrajnie roznej intensywnosci (rozne materialy) - NIE powinny
    # polaczyc sie w jeden klaster mimo bliskosci.
    points = np.array(
        [
            [0.0, 0.0, 0.3, 20.0],
            [0.02, 0.0, 0.3, 240.0],
        ],
        dtype=np.float32,
    )

    clusters = cluster_obstacles(points, min_points=1)

    assert len(clusters) == 2


def test_similar_intensity_still_merges_when_close():
    # Ten sam scenariusz przestrzenny, ale intensywnosc bliska - powinny
    # sie polaczyc jak dawniej (czysta odleglosc).
    points = np.array(
        [
            [0.0, 0.0, 0.3, 100.0],
            [0.02, 0.0, 0.3, 110.0],
        ],
        dtype=np.float32,
    )

    clusters = cluster_obstacles(points, min_points=1)

    assert len(clusters) == 1


def test_mean_intensity_is_computed_correctly():
    points = np.array(
        [
            [0.0, 0.0, 0.3, 50.0],
            [0.01, 0.0, 0.3, 100.0],
            [0.0, 0.01, 0.3, 150.0],
        ],
        dtype=np.float32,
    )

    clusters = cluster_obstacles(points, min_points=1)

    assert len(clusters) == 1
    assert clusters[0].mean_intensity == pytest.approx((50.0 + 100.0 + 150.0) / 3)


def test_cluster_bbox_and_centroid_are_correct():
    points = _with_intensity(
        np.array(
            [
                [0.0, 0.0, 0.0],
                [0.02, 0.0, 0.4],
                [0.0, 0.02, 0.2],
            ]
        )
    )

    clusters = cluster_obstacles(points, min_points=1)

    assert len(clusters) == 1
    c = clusters[0]
    assert c.x_min == pytest.approx(0.0)
    assert c.x_max == pytest.approx(0.02)
    assert c.z_min == pytest.approx(0.0)
    assert c.z_max == pytest.approx(0.4)
    assert c.point_count == 3
    assert c.centroid_z == pytest.approx((0.0 + 0.4 + 0.2) / 3)
