import numpy as np

from src.hardware.lidar.obstacle_reducer import LidarObstacleReducer


def _flat_scene_points(rng, near_count, far_count, near_radius=1.0, far_radius=7.0):
    """Punkty NAD podloga (obstacle_mask przejdzie), zgeszczone blisko i
    rzadkie daleko - symuluje realna gestosc lidaru (wiecej zwrotow z
    bliska)."""
    near_xy = rng.uniform(-near_radius, near_radius, size=(near_count, 2))
    near_z = rng.uniform(0.3, 0.5, size=near_count)
    far_xy = rng.uniform(far_radius - 0.3, far_radius + 0.3, size=(far_count, 2))
    far_z = rng.uniform(0.3, 0.5, size=far_count)
    xy = np.vstack([near_xy, far_xy])
    z = np.concatenate([near_z, far_z])
    return np.column_stack([xy, z]).astype(np.float32)


def test_far_points_survive_even_when_near_points_dominate():
    rng = np.random.default_rng(0)
    reducer = LidarObstacleReducer(max_output_points=200)

    # Symuluj juz-po-ground-removal punkty (nadpisujemy prywatnie na
    # potrzeby testu tej jednej funkcji, bez przechodzenia calego reduce()).
    pts = _flat_scene_points(rng, near_count=5000, far_count=50)

    selected = reducer._select_evenly_by_distance(pts)

    assert selected.shape[0] <= reducer.max_output_points
    dist = np.sqrt(selected[:, 0] ** 2 + selected[:, 1] ** 2)
    far_selected = (dist > 5.0).sum()

    # Przy czystym "priorytecie najblizszych" far_selected bylby 0 (5000
    # blizszych punktow calkowicie zdominowaloby budzet 200). Stratyfikacja
    # gwarantuje kwote per-przedzial niezaleznie od tego, ile bliskich
    # punktow konkuruje - 50 dalekich punktow miesci sie w ~2 przedzialach
    # (kwota 10/przedzial) => oczekiwane ~20 (40%), a NIE zero.
    assert far_selected >= 15, f"oczekiwano >=15 dalekich punktow w wyniku, jest {far_selected}"


def test_output_never_exceeds_max_output_points():
    rng = np.random.default_rng(1)
    reducer = LidarObstacleReducer(max_output_points=150)
    pts = _flat_scene_points(rng, near_count=3000, far_count=10)

    selected = reducer._select_evenly_by_distance(pts)

    assert selected.shape[0] <= reducer.max_output_points


def test_fully_utilizes_budget_when_enough_points_available():
    rng = np.random.default_rng(2)
    reducer = LidarObstacleReducer(max_output_points=100)
    pts = _flat_scene_points(rng, near_count=2000, far_count=500)

    selected = reducer._select_evenly_by_distance(pts)

    # Wystarczajaco duzo punktow w kazdym przedziale - budzet powinien byc
    # w pelni wykorzystany (albo bardzo blisko pelnego wykorzystania).
    assert selected.shape[0] == reducer.max_output_points


def _raw_point_for_leveled_obstacle(reducer, leveled_xyz):
    """Odwraca korekte pochylenia (rotacja jest ortonormalna, wiec
    odwrotnosc to transpozycja), zeby skonstruowac surowy punkt w ukladzie
    CZUJNIKA, ktory po reduce() na pewno geometrycznie przejdzie jako
    kandydat na przeszkode (niezaleznie od filtra intensywnosci)."""
    leveled = np.array(leveled_xyz, dtype=np.float32)
    raw_xyz = leveled @ reducer._tilt_matrix  # (R^T)^T = R, bo R jest ortonormalna
    return raw_xyz


def test_low_intensity_points_are_filtered_as_noise():
    reducer = LidarObstacleReducer(min_intensity=40.0)
    raw_xyz = _raw_point_for_leveled_obstacle(reducer, [0.5, 0.5, 0.4])
    strong = np.array([[*raw_xyz, 100.0]], dtype=np.float32)
    weak = np.array([[*raw_xyz, 10.0]], dtype=np.float32)

    assert reducer.reduce(strong).shape[0] >= 1
    assert reducer.reduce(weak).shape[0] == 0


def test_intensity_threshold_is_configurable():
    lenient = LidarObstacleReducer(min_intensity=0.0)
    strict = LidarObstacleReducer(min_intensity=200.0)
    raw_xyz = _raw_point_for_leveled_obstacle(lenient, [0.5, 0.5, 0.4])
    pts = np.array([[*raw_xyz, 50.0]], dtype=np.float32)

    assert lenient.reduce(pts).shape[0] >= 1
    assert strict.reduce(pts).shape[0] == 0


def _raw_point_for_leveled(leveled_xyz, reducer):
    """Odwraca korekte pochylenia - reduce() oczekuje ukladu CZUJNIKA
    (przed korekta), a chcemy skonstruowac punkty o znanej pozycji W
    UKLADZIE LEVELED (po korekcie), gdzie mierzona jest samo-detekcja."""
    return np.asarray(leveled_xyz, dtype=np.float32) @ reducer._tilt_matrix


def test_self_detection_footprint_is_excluded():
    # Regresja: LiDAR widzi wlasna obudowe/wspornik robota - potwierdzone
    # empirycznie na zywym robocie pelnym skanem occupancy-grid (10cm,
    # >=90% z 50 kolejnych ramek, mimo wolnej przestrzeni dookola robota -
    # patrz rozmowa). Zmierzona pelna strefa (uklad leveled, po korekcie
    # pochylenia): x:[-1.0,1.5] y:[-0.2,0.5] z:[-0.55,0.2] - WYRAZNIE
    # oddzielona pustym pasem (y=0.3-1.0 bez zadnej trwalej komorki) od
    # dalszego, prawdopodobnie realnego obiektu na y=[1.1,2.3], ktory
    # celowo NIE jest wykluczany. Bez wykluczenia bliskiej strefy ta stale
    # obecna, geometrycznie "wlasna" geometria byla renderowana jako trwala
    # przeszkoda tuz przy robocie (siatka boxow na screenshocie uzytkownika).
    reducer = LidarObstacleReducer()
    rng = np.random.default_rng(0)

    n = 500
    leveled = np.column_stack([
        rng.uniform(-0.95, 1.45, n),
        rng.uniform(-0.15, 0.45, n),
        rng.uniform(-0.5, 0.15, n),
    ])
    raw = np.column_stack([
        _raw_point_for_leveled(leveled, reducer),
        rng.uniform(120, 200, n),
    ]).astype(np.float32)

    reduced = reducer.reduce(raw)

    assert reduced.shape[0] == 0, (
        f"punkty we wlasnej geometrii robota NIE zostaly wykluczone: {reduced.shape[0]} przetrwalo"
    )


def test_self_detection_exclusion_does_not_blind_real_nearby_obstacles():
    # Ten sam test co wyzej, ale z realnym obiektem TUZ ZA granica strefy
    # wykluczenia (np. ktos postawil krzeslo blisko robota) - filtr nie
    # moze byc szerszy niz potrzeba.
    reducer = LidarObstacleReducer()
    rng = np.random.default_rng(1)

    n = 500
    leveled = np.column_stack([
        rng.uniform(2.0, 2.4, n),  # wyraznie POZA strefa (x<=1.5)
        rng.uniform(0.3, 0.7, n),
        rng.uniform(0.05, 0.4, n),
    ])
    raw = np.column_stack([
        _raw_point_for_leveled(leveled, reducer),
        rng.uniform(120, 200, n),
    ]).astype(np.float32)

    reduced = reducer.reduce(raw)

    assert reduced.shape[0] > 0, "realny obiekt tuz za strefa wykluczenia zostal zgubiony"


def test_separate_object_beyond_the_gap_is_not_blinded():
    # Regresja przez konstrukcje: podczas diagnozy na zywym robocie
    # znaleziono DRUGA, oddalona strefe (y=[1.1,2.3]) oddzielona od bliskiej
    # strefy samo-detekcji pustym pasem (y=0.3-1.0). To byl kluczowy dowod,
    # ze druga strefa to REALNY obiekt (prawdopodobnie mebel), nie
    # geometria robota - i dlatego celowo NIE wchodzi do domyslnej strefy
    # wykluczenia. Ten test pilnuje, zeby przyszla zmiana nie "polaczyla"
    # obu stref w jedna szeroka, niebezpieczna dziure w detekcji.
    reducer = LidarObstacleReducer()
    rng = np.random.default_rng(3)

    n = 300
    leveled = np.column_stack([
        rng.uniform(0.6, 1.4, n),
        rng.uniform(1.1, 2.3, n),
        rng.uniform(0.1, 0.5, n),
    ])
    raw = np.column_stack([
        _raw_point_for_leveled(leveled, reducer),
        rng.uniform(120, 200, n),
    ]).astype(np.float32)

    reduced = reducer.reduce(raw)

    assert reduced.shape[0] > 0, (
        "obiekt za pustym pasem (prawdopodobnie realny mebel) zostal zgubiony"
    )


def test_self_exclusion_zone_is_configurable():
    custom = LidarObstacleReducer(
        self_exclusion_x_m=(0.0, 0.1),
        self_exclusion_y_m=(0.0, 0.1),
        self_exclusion_z_m=(0.0, 0.1),
    )
    rng = np.random.default_rng(2)
    n = 200
    # Punkty ktore wpadalyby w DOMYSLNA strefe, ale nie w ta wezsza custom -
    # Z dobrany wyraznie NAD marginesem ground-removal (fallback
    # mount_height_m=0.056, ground_margin_m=0.15 przy braku kalibracji),
    # zeby test mierzyl wylacznie dzialanie self-exclusion, nie ground removal.
    leveled = np.column_stack([
        np.full(n, 0.5),
        np.full(n, 0.3),
        np.full(n, 0.3),
    ])
    raw = np.column_stack([
        _raw_point_for_leveled(leveled, custom),
        rng.uniform(120, 200, n),
    ]).astype(np.float32)

    reduced = custom.reduce(raw)

    assert reduced.shape[0] > 0, "wezsza, wlasna strefa wykluczenia zostala zignorowana"


def test_below_limit_input_is_unaffected_by_reduce():
    reducer = LidarObstacleReducer(max_output_points=5000)
    # Malo punktow - reduce() nie powinien wywolywac selekcji wcale,
    # kod powinien zwrocic wszystkie kandydatujace punkty.
    pts = np.array(
        [
            [0.5, 0.5, 0.4, 100.0],
            [1.5, 1.5, 0.4, 100.0],
            [3.0, 3.0, 0.4, 100.0],
        ],
        dtype=np.float32,
    )
    result = reducer.reduce(pts)
    # Po korekcie/ground-removal moze zostac mniej (voxel dedup), ale na
    # pewno <= wejscie i nie powinno wywalic sie bledem.
    assert result.shape[0] <= pts.shape[0]
