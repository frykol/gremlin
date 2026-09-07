"""
Dopasowanie plaszczyzny podlogi/stolu metoda RANSAC, zamiast polegania na
sztywnym marginesie wysokosci kompensujacym niedokladnosc recznie
skalibrowanej korekty pochylenia (patrz obstacle_reducer.py).

Uzasadnienie: nawet po korekcie orientacji 3-osiowej (dobranej WIZUALNIE w
viewerze), plaszczyzna podlogi/stolu w "poziomym" ukladzie nie jest idealnie
plaska - ma resztkowy, maly gradient (potwierdzone empirycznie: rozrzut
Z ~14cm na realnych danych L1). Dopasowanie plaszczyzny wprost z danych
(zamiast zakladania Z=const) usuwa te niedokladnosc u zrodla, pozwalajac
na duzo ciasniejszy margines wysokosci przy ground removal.
"""

from typing import Optional, Tuple

import numpy as np


DEFAULT_MAX_NORMAL_TILT_DEG = 30.0


def fit_ground_plane(
    points: np.ndarray,
    n_iterations: int = 200,
    distance_threshold_m: float = 0.03,
    min_inlier_ratio: float = 0.3,
    rng: Optional[np.random.Generator] = None,
    max_normal_tilt_deg: Optional[float] = DEFAULT_MAX_NORMAL_TILT_DEG,
) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """
    points: (N,3) chmura punktow w ukladzie PO korekcie pochylenia (Z ~ w
    gore) - RANSAC szuka dominujacej plaszczyzny SPOSROD ~poziomych.

    max_normal_tilt_deg: maksymalne odchylenie normalnej plaszczyzny od osi
    Z (pionu). None wylacza filtr (dowolna dominujaca plaszczyzna).

    Filtr jest KONIECZNY, nie kosmetyczny: bez niego "najwieksza plaska
    powierzchnia w polu widzenia" to czesto SCIANA, nie podloga (zmierzone:
    scena z 2000 pkt sciany i 800 pkt podlogi dopasowuje sciane z |n_z|=0.001).
    Taka "podloga" odwraca cala detekcje w obstacle_reducer.reduce() - sciana
    znika jako grunt, a podloga staje sie przeszkoda - i to CICHO, bo
    kalibracja zglasza sukces. Podloga z definicji jest ~pozioma, wiec
    ograniczenie normalnej do stozka wokol pionu odsiewa ten przypadek u
    zrodla. 30 stopni to duzy zapas na resztkowy blad recznej korekty
    pochylenia (zmierzony rozrzut ~14cm to kilka stopni), a wciaz daleko od
    powierzchni pionowych.

    Zwraca (normal, point_on_plane): normal jest znormalizowanym wektorem
    (3,), point_on_plane to centroid inlierow (3,). Odleglosc dowolnego
    punktu P od plaszczyzny (ze znakiem, dodatnia = nad plaszczyzna w
    kierunku normal) to (P - point_on_plane) @ normal.

    Zwraca None, jesli nie znaleziono wystarczajaco dobrego dopasowania
    (za malo punktow, zaden model nie osiagnal min_inlier_ratio, albo zadna
    dostatecznie pozioma plaszczyzna nie istnieje) - wywolujacy powinien
    wtedy zostac przy poprzedniej/domyslnej kalibracji.
    """
    if rng is None:
        rng = np.random.default_rng()

    points = np.asarray(points, dtype=np.float64)
    n = points.shape[0]
    if n < 50:
        return None

    # |n_z| >= cos(max_tilt) <=> normalna miesci sie w stozku wokol pionu.
    min_abs_normal_z = (
        float(np.cos(np.radians(max_normal_tilt_deg)))
        if max_normal_tilt_deg is not None
        else None
    )

    best_inlier_count = 0
    best_seed_plane = None

    for _ in range(n_iterations):
        idx = rng.choice(n, size=3, replace=False)
        p0, p1, p2 = points[idx]
        v1 = p1 - p0
        v2 = p2 - p0
        normal = np.cross(v1, v2)
        norm_len = np.linalg.norm(normal)
        if norm_len < 1e-9:
            continue  # trzy wspolliniowe punkty - nie definiuja plaszczyzny
        normal = normal / norm_len

        # Odsiew kandydatow niepoziomych PRZED liczeniem inlierow - dzieki
        # temu "najlepszy" model jest najlepszy sposrod dopuszczalnych, a
        # nie globalnie (inaczej sciana i tak by wygrala i zablokowala wynik).
        if min_abs_normal_z is not None and abs(normal[2]) < min_abs_normal_z:
            continue

        dist = np.abs((points - p0) @ normal)
        inlier_count = int((dist < distance_threshold_m).sum())
        if inlier_count > best_inlier_count:
            best_inlier_count = inlier_count
            best_seed_plane = (normal, p0)

    if best_seed_plane is None or best_inlier_count < n * min_inlier_ratio:
        return None

    # Dopracowanie: dopasowanie najmniejszych kwadratow (SVD) na WSZYSTKICH
    # inlierach najlepszego modelu-nasiona, nie tylko na probce 3 punktow -
    # znaczaco stabilniejsze niz surowy wynik RANSAC.
    seed_normal, seed_point = best_seed_plane
    dist = (points - seed_point) @ seed_normal
    inlier_mask = np.abs(dist) < distance_threshold_m
    inlier_pts = points[inlier_mask]

    centroid = inlier_pts.mean(axis=0)
    centered = inlier_pts - centroid
    # Normal plaszczyzny = kierunek najmniejszej wariancji (ostatni wektor
    # z SVD odpowiadajacy najmniejszej wartosci osobliwej).
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    refined_normal = vh[-1]

    if np.dot(refined_normal, seed_normal) < 0:
        refined_normal = -refined_normal

    # Dopracowanie SVD moglo (na skosnym zbiorze inlierow) wyprowadzic
    # normalna poza dopuszczalny stozek - wtedy wynik nie jest juz
    # plaszczyzna podlogi i lepiej nie zwracac nic, niz zwrocic zla
    # kalibracje (wywolujacy zostanie przy poprzedniej/fallbacku).
    if min_abs_normal_z is not None and abs(refined_normal[2]) < min_abs_normal_z:
        return None

    return refined_normal.astype(np.float32), centroid.astype(np.float32)
