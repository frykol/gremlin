"""
Redukcja chmury punktow LiDAR 3D do zredukowanej listy przeszkod, w pelni
zwektoryzowana (numpy), bez petli po punktach i bez zaleznosci od
sklearn/PCL/Open3D.

Potok: filtr intensywnosci (szum) -> korekta pochylenia montazu -> ground
removal wzgledem plaszczyzny dopasowanej z danych (RANSAC, patrz
ground_plane.py) lub fallbackowego Z-cut -> deduplikacja siatka wokselowa
(1 REALNY punkt na kostke, nie interpolowana srednia) -> twardy limit
liczby punktow rozlozony PROPORCJONALNIE po przedzialach odleglosci (nie
"najblizsze pierwsze" - blizka, gesta chmura potrafila zjesc caly budzet).

Zmierzone na Raspberry Pi 5 (N=30000 -> 1500 pkt): srednio ~13 ms/klatke.
"""

import numpy as np

from .ground_plane import fit_ground_plane


DEFAULT_DEPTH_SMEAR_BEARING_BIN_DEG = 2.0
DEFAULT_DEPTH_SMEAR_DEPTH_BIN_M = 0.5
DEFAULT_DEPTH_SMEAR_MIN_OCCUPIED_BINS = 4
DEFAULT_DEPTH_SMEAR_MERGE_GAP_BINS = 1


def _filter_depth_smeared_rays(
    candidates: np.ndarray,
    bearing_bin_deg: float = DEFAULT_DEPTH_SMEAR_BEARING_BIN_DEG,
    depth_bin_m: float = DEFAULT_DEPTH_SMEAR_DEPTH_BIN_M,
    min_occupied_bins: int = DEFAULT_DEPTH_SMEAR_MIN_OCCUPIED_BINS,
    merge_gap_bins: int = DEFAULT_DEPTH_SMEAR_MERGE_GAP_BINS,
) -> np.ndarray:
    """
    candidates: (N,4) x,y,z,intensity w ukladzie leveled, PO ground removal.

    Dzieli punkty na waskie sektory azymutu (bearing = atan2(x,y)). W kazdym
    sektorze liczy, ile ROZLACZNYCH przedzialow zasiegu (depth_bin_m
    szerokie) jest zajete - NIE poprzez przerwy miedzy sasiednimi punktami
    (to zawodzi przy duzej gestosci, patrz nizej), tylko przez zliczenie
    UNIKALNYCH zajetych binow, co jest niezalezne od tego, ile punktow
    wpada do kazdego z nich.

    Dlaczego licznik binow, nie przerwy miedzy punktami: pierwsza wersja
    tego filtra liczyla "warstwy" przez przerwy > 0.4m miedzy kolejnymi
    punktami posortowanymi wg zasiegu. Dzialalo to na rzadkim,
    zdziesiatkowanym zbiorze wyjsciowym (~4000 pkt), ale zawodzilo na
    GESTYM zbiorze kandydatow (dziesiatki tysiecy pkt) - przy takiej
    gestosci przerwy >0.4m prawie nigdy nie wystepuja (kolejne punkty
    dziela zaledwie kilka cm), wiec caly "rozmazany" zasieg 0.5-8m zlewal
    sie w JEDNA warstwe i nic nie bylo odrzucane (zmierzone: tylko 4.8%
    usuniete, mimo ewidentnego widma). Zliczanie ZAJETYCH BINOW jest
    odporne na gestosc: potwierdzony REALNY obiekt (bearing 28-40st, patrz
    rozmowa) zajmowal 1-2 biny 0.5m (rozpietosc ~0.4m) NIEZALEZNIE od tego,
    czy mial 40 czy 4000 punktow - podczas gdy widmowe sektory zajmowaly
    12-14 binow (rozpietosc 6-7.5m), rowniez niezaleznie od gestosci.

    Sektor z >= min_occupied_bins zajetymi binami jest podejrzany o
    rozpraszanie/multipath (patrz komentarz w reduce()) - zostaja w nim
    TYLKO punkty w STALYM oknie (merge_gap_bins+1)*depth_bin_m od
    najblizszego zwrotu, pozostale sa odrzucane.

    UWAGA na projekt tego okna: zmierzony na zywych danych fenomen
    rozmazania zajmuje WSZYSTKIE biny w zakresie CIAGLE, bez zadnych przerw
    miedzy nimi (12-14 z ~16 mozliwych binow na 0-8m, zero pustych binow
    pomiedzy) - proba "polaczenia sasiadujacych zajetych binow" (idac od
    najblizszego, dopoki nie trafi sie prawdziwa przerwa) NIE ma wiec czego
    znalezc i przechodzi przez caly zasieg bez ciecia (zmierzone: tylko
    ~11% usuniete zamiast oczekiwanej wiekszosci). Dlatego okno jest
    bezwarunkowo STALEJ szerokosci od najblizszego zwrotu, a nie
    "podazajace za lancuchem zajetych binow".
    """
    n = candidates.shape[0]
    if n == 0:
        return candidates

    x, y = candidates[:, 0], candidates[:, 1]
    rng = np.hypot(x, y)
    bearing_deg = np.degrees(np.arctan2(x, y))
    bearing_bin = np.floor(bearing_deg / bearing_bin_deg).astype(np.int64)
    depth_bin = np.floor(rng / depth_bin_m).astype(np.int64)

    keep = np.ones(n, dtype=bool)
    order = np.argsort(bearing_bin, kind="stable")
    sorted_bearing = bearing_bin[order]
    boundaries = np.flatnonzero(np.diff(sorted_bearing)) + 1
    group_starts = np.concatenate(([0], boundaries))
    group_ends = np.concatenate((boundaries, [n]))

    for start, end in zip(group_starts, group_ends):
        idx = order[start:end]
        occupied = np.unique(depth_bin[idx])
        if occupied.size < min_occupied_bins:
            continue

        # Stale okno (merge_gap_bins+1)*depth_bin_m od najblizszego zwrotu -
        # patrz uwaga w docstringu (dlaczego NIE "podazaj za lancuchem
        # zajetych binow": zmierzony fenomen jest ciagly, bez przerw).
        nearest_bin = occupied.min()
        cutoff_bin = nearest_bin + merge_gap_bins

        far_mask = depth_bin[idx] > cutoff_bin
        drop_idx = idx[far_mask]
        keep[drop_idx] = False

    return candidates[keep]


def _in_box_mask(points: np.ndarray, x_range, y_range, z_range) -> np.ndarray:
    """
    Maska punktow (N,3) wewnatrz osiowo-wyrownanego prostopadloscianu.
    Kazdy zakres to (min, max) albo None (os nieograniczona - caly zakres
    przechodzi na tej osi).
    """
    mask = np.ones(points.shape[0], dtype=bool)
    for axis, axis_range in enumerate((x_range, y_range, z_range)):
        if axis_range is None:
            continue
        lo, hi = axis_range
        mask &= (points[:, axis] >= lo) & (points[:, axis] <= hi)
    return mask


class LidarObstacleReducer:
    """
    Redukuje surowa chmure punktow LiDAR (N,4: x,y,z,intensity) w ukladzie
    czujnika do zredukowanej listy punktow-przeszkod (M,4), M <=
    max_output_points, gotowej dla planera unikania kolizji i klastrowania
    (obstacle_clustering.py).

    Zalozenia ukladu wspolrzednych wejsciowych (przed korekta): x=prawo,
    y=przod, z=w gore w ramce CZUJNIKA (a wiec przechylonej wzgledem
    poziomu o katy tilt_x/y/z_deg). Wyjscie jest w poziomym ukladzie ROBOTA
    po tej samej korekcie (x=prawo, y=przod, z=w gore) - patrz uwaga w
    reduce() o tym, dlaczego Z NIE jest nadpisywane wysokoscia nad
    dopasowana plaszczyzna.
    """

    __slots__ = (
        "mount_height_m",
        "ground_margin_m",
        "calibrated_ground_margin_m",
        "max_obstacle_height_m",
        "voxel_size_m",
        "max_output_points",
        "min_intensity",
        "self_exclusion_x_m",
        "self_exclusion_y_m",
        "self_exclusion_z_m",
        "_tilt_matrix",
        "_ground_normal",
        "_ground_point",
    )

    def __init__(
        self,
        tilt_x_deg: float = -122.0,
        tilt_y_deg: float = 19.0,
        tilt_z_deg: float = -11.0,
        # Filtr szumu: odbicia o intensywnosci ponizej tego progu sa
        # odrzucane PRZED reszta pipeline'u (nie licza sie jako kandydaci
        # na przeszkody). Skala intensywnosci Unitree L1 to 0-255; na
        # realnych danych (650k punktow) ponizej ~50 jest wyrazny, cienki
        # "ogon" bardzo slabych/zaszumionych odbic (<1% danych) przed
        # glownym korpusem rozkladu (mediana ~148) - to sa najbardziej
        # niewiarygodne pomiary (odbicia rozproszone/wieloscienzkowe), nie
        # realne, ale slabo odbijajace obiekty.
        min_intensity: float = 40.0,
        # Fallback UZYWANY TYLKO PRZED skalibrowaniem plaszczyzny (patrz
        # calibrate_ground() ponizej) - zmierzone empirycznie z live danych
        # L1 (mediana Z blisko robota), nie zalozone "na oko" jak
        # pierwotne 0.17.
        mount_height_m: float = 0.056,
        # Fallback margines PRZED kalibracja - duzy, bo bez dopasowanej
        # plaszczyzny trzeba kompensowac niedokladnosc recznie dobranej
        # (wizualnie) korekty pochylenia (rozrzut Z ~14cm na realnych
        # danych). PO kalibracji uzywany jest calibrated_ground_margin_m
        # (dużo ciasniejszy), bo plaszczyzna jest dopasowana wprost z danych.
        ground_margin_m: float = 0.15,
        # Margines PO skalibrowaniu plaszczyzny (fit_ground_plane) - moze
        # byc duzo ciasniejszy, bo odleglosc do plaszczyzny nie cierpi juz
        # na blad reczej korekty pochylenia.
        calibrated_ground_margin_m: float = 0.05,
        max_obstacle_height_m: float = 1.20,
        # Rozdzielczosc przestrzenna po deduplikacji. 8cm (poprzednia
        # wartosc) bylo grubsze niz wiele realnych przeszkod (kubek, noga
        # krzesla) i to WOKSEL, nie limit punktow, byl wezszym gardlem
        # szczegolowosci: przy 8cm przez potok przechodzilo ~1400-1700
        # punktow NIEZALEZNIE od max_output_points (zmierzone: budzet 1500
        # i 5000 dawaly tyle samo). Zejscie do 3cm podnioslo rozdzielczosc
        # detekcji (najmniejszy rozstaw dwoch rozroznialnych obiektow na
        # 2m) z 0.35m do 0.25m - patrz tests/test_detection_resolution.py.
        voxel_size_m: float = 0.03,
        # Podniesiony razem z wokselem - przy 3cm przez potok przechodzi
        # ~2400 punktow, wiec stary sufit 1500 obcinalby zysk z drobniejszej
        # siatki. Koszt calego potoku zmierzony na 40.6ms przy budzecie
        # 200ms/tick (obstacle_loop), wiec jest zapas.
        max_output_points: int = 4000,
        # Strefa (uklad LEVELED, po korekcie pochylenia), w ktorej LiDAR
        # widzi WLASNA obudowe/wspornik robota, a nie realne otoczenie.
        # Zmierzona empirycznie na zywym robocie metoda occupancy-grid:
        # klastry obecne w 100% ramek (dwie oddzielne proby, 40-50 ramek
        # kazda, ~8-9s) mimo potwierdzonej wolnej przestrzeni dookola
        # robota - jednoznaczny podpis sztywno zamocowanej, nieruchomej
        # wzgledem czujnika czesci (patrz rozmowa/brainstorming). Bez tego
        # wykluczenia ta stale obecna "przeszkoda" tuz przy robocie byla
        # renderowana jako duzy, pokratkowany blok (widoczny na screenshocie
        # uzytkownika). Zmierzone DWIE oddzielne strefy - dodatnia (wspornik
        # z jednej strony) i ujemna X (wspornik/element z drugiej) - stad
        # Finalny zasieg ustalony pelnym skanem occupancy-grid (10cm,
        # >=90% z 50 ramek) obszaru x:[-2.5,2.5] y:[-1.0,2.5]: bliska strefa
        # (ta wlasnie) jest OD DZIELONA wyraznie pustym pasem (y=0.3-1.0 bez
        # ANI JEDNEJ trwalej komorki) od DALSZEGO obiektu na y=[1.1,2.3] -
        # ten drugi NIE jest tu wliczony, bo pusty pas dowodzi, ze to
        # ODDZIELNY, prawdopodobnie realny (nieruchomy mebel), a nie
        # geometria robota - wlaczenie go stworzyloby niebezpieczny martwy
        # punkt. Kazdy zakres to (min, max) w metrach; None wylacza dana os
        # (domyslnie brak wykluczenia na tej osi).
        self_exclusion_x_m: tuple = (-1.0, 1.5),
        self_exclusion_y_m: tuple = (-0.2, 0.5),
        # Rozszerzone w dol po kolejnej weryfikacji na zywo: fragmenty tej
        # samej bliskiej strefy (x/y jak wyzej) mialy z siegajace -0.93,
        # glebiej niz pierwotnie zmierzone -0.55 - inna czesc tej samej
        # sztywnej konstrukcji pod czujnikiem.
        self_exclusion_z_m: tuple = (-1.0, 0.2),
    ):
        self.mount_height_m = mount_height_m
        self.ground_margin_m = ground_margin_m
        self.calibrated_ground_margin_m = calibrated_ground_margin_m
        self.max_obstacle_height_m = max_obstacle_height_m
        self.voxel_size_m = voxel_size_m
        self.max_output_points = max_output_points
        self.min_intensity = min_intensity
        self.self_exclusion_x_m = self_exclusion_x_m
        self.self_exclusion_y_m = self_exclusion_y_m
        self.self_exclusion_z_m = self_exclusion_z_m
        self._ground_normal = None
        self._ground_point = None

        # Pelna korekta orientacji montazu na 3 osiach (X, Y, Z), dobrana
        # recznie na zywo w viewerze LiDAR-u (site/public/lidar/js/
        # pointcloud.js, BASE_TILT_X/Y/Z_DEG) - jedna os (dawne tilt_deg=35)
        # nie odpowiadala rzeczywistemu montazowi. Rotacje skladane w TEJ
        # SAMEJ kolejnosci co w JS: najpierw X (pitch), potem Y (yaw), na
        # koncu Z (roll) - M = Rz @ Ry @ Rx.
        rx, ry, rz = np.radians([tilt_x_deg, tilt_y_deg, tilt_z_deg])
        cx, sx = np.cos(rx), np.sin(rx)
        cy, sy = np.cos(ry), np.sin(ry)
        cz, sz = np.cos(rz), np.sin(rz)

        r_x = np.array([[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]])
        r_y = np.array([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]])
        r_z = np.array([[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]])

        self._tilt_matrix = (r_z @ r_y @ r_x).astype(np.float32)

    def calibrate_ground(self, points: np.ndarray) -> bool:
        """
        Dopasowuje realna plaszczyzne podlogi/stolu z danych (RANSAC + SVD,
        patrz ground_plane.py) zamiast polegac na stalym mount_height_m i
        zalozeniu, ze plaszczyzna po korekcie pochylenia jest idealnie
        Z=const. Wywolujacy decyduje KIEDY kalibrowac (np. raz na starcie,
        albo okresowo) - ta klasa sama niczego nie inicjuje.

        points: surowe punkty w ukladzie CZUJNIKA (przed korekta - ta sama
        konwencja co reduce()), (N,3) LUB (N,4) z dodatkowa kolumna
        intensity na koncu (ignorowana tutaj - dopasowanie plaszczyzny jest
        czysto geometryczne).

        Zwraca True, jesli kalibracja sie powiodla (od teraz reduce() uzywa
        dopasowanej plaszczyzny + calibrated_ground_margin_m), False jesli
        dopasowanie nie powiodlo sie (za malo punktow, brak wyraznej
        dominujacej plaszczyzny, albo znaleziona plaszczyzna nie jest
        ~pozioma - np. robot stoi przodem do sciany, patrz
        max_normal_tilt_deg w ground_plane.py) - poprzednia kalibracja
        (jesli byla) albo fallback mount_height_m/ground_margin_m zostaje
        bez zmian. Wywolujacy powinien ponawiac probe z backoffem, a nie w
        kazdym ticku (RANSAC na 30k punktach to ~41ms) - patrz
        GROUND_RECALIBRATION_RETRY_INTERVAL_S w backend/lidar/app.py.
        """
        if points.size == 0:
            return False

        xyz = np.asarray(points, dtype=np.float32)[:, :3]
        leveled = xyz @ self._tilt_matrix.T
        result = fit_ground_plane(leveled)
        if result is None:
            return False

        normal, point_on_plane = result
        # Normal ma wskazywac "w gore" wzgledem przyblizonego ukladu z
        # korekty pochylenia - bez tego przeszkody i podloga moglyby
        # zamienic sie znakiem odleglosci.
        if normal[2] < 0:
            normal = -normal
        self._ground_normal = normal
        self._ground_point = point_on_plane
        return True

    @property
    def is_calibrated(self) -> bool:
        return self._ground_normal is not None

    def reduce(self, points: np.ndarray) -> np.ndarray:
        """
        points: (N,4) - x,y,z,intensity w ukladzie CZUJNIKA. Kolumna
        intensity jest WYMAGANA (nie opcjonalna) - uzywana do wczesnego
        odsiania najslabszych/najbardziej zaszumionych odbic (patrz
        min_intensity) ORAZ przenoszona do wyjscia (4. kolumna), zeby
        klastrowanie (obstacle_clustering.py) moglo jej uzyc jako
        dodatkowego kryterium (punkty o bardzo roznej intensywnosci =
        rozne materialy, nie powinny laczyc sie w jeden klaster mimo
        bliskosci przestrzennej).

        Zwraca (M,4): x,y,z,intensity w poziomym ukladzie robota.
        """
        if points.size == 0:
            return np.empty((0, 4), dtype=np.float32)

        points = np.asarray(points, dtype=np.float32)

        # 0) Filtr intensywnosci - odrzuc najslabsze/najbardziej zaszumione
        # odbicia PRZED reszta pipeline'u (tansze niz robic to po korekcie/
        # ground-removal, i usuwa szum, ktory inaczej moglby zostac blednie
        # uznany za nisko polozona przeszkode).
        intensity_mask = points[:, 3] >= self.min_intensity
        points = points[intensity_mask]
        if points.shape[0] == 0:
            return np.empty((0, 4), dtype=np.float32)

        xyz = points[:, :3]
        intensity = points[:, 3]

        # 1) Korekta pochylenia montazu -> poziomy uklad robota (x/y).
        # WAZNE: to jest DOKLADNIE ta sama korekta (te same katy X/Y/Z) co
        # w frontendzie (site/public/lidar/js/pointcloud.js, BASE_TILT_*) -
        # wyjscie reduce() MUSI zostac w tym ukladzie (rowniez Z), zeby
        # bounding boxy przeszkod (obstacle_overlay.js) pokrywaly sie z
        # widoczna chmura punktow. Dopasowana plaszczyzna (ground_normal)
        # jest NACHYLONA wzgledem tego ukladu (bo koryguje resztkowy blad
        # recznej korekty), wiec uzywamy jej TYLKO do decyzji "czy to
        # podloga" (height ponizej), a nie do nadpisywania Z wyjsciowego -
        # inaczej Z zalezaloby tez od X/Y (przez iloczyn skalarny z
        # normalna), przekrzywiajac boxy wzgledem punktow.
        leveled = xyz @ self._tilt_matrix.T

        # 1b) Wykluczenie WLASNEJ geometrii robota (patrz
        # self_exclusion_*_m w __init__) - musi byc PRZED ground removal,
        # bo strefa jest zdefiniowana w tym samym ukladzie leveled.
        self_mask = _in_box_mask(
            leveled, self.self_exclusion_x_m, self.self_exclusion_y_m, self.self_exclusion_z_m
        )
        if np.any(self_mask):
            keep = ~self_mask
            leveled = leveled[keep]
            intensity = intensity[keep]
        if leveled.shape[0] == 0:
            return np.empty((0, 4), dtype=np.float32)

        # 2) Wysokosc nad "podloga" - UZYWANA TYLKO do progu ground-removal
        # ponizej, NIE trafia do wyjscia. Jesli mamy skalibrowana
        # plaszczyzne, liczymy realna odleglosc (ze znakiem) do niej -
        # odporne na resztkowy blad recznej korekty pochylenia. Bez
        # kalibracji - fallback na stary, przyblizony sposob (staly
        # mount_height_m).
        if self._ground_normal is not None:
            height = (leveled - self._ground_point) @ self._ground_normal
            margin = self.calibrated_ground_margin_m
        else:
            height = leveled[:, 2] + self.mount_height_m
            margin = self.ground_margin_m

        # 3) Ground removal (Z-cut) - jeden zwektoryzowany warunek logiczny.
        obstacle_mask = (height > margin) & (height < self.max_obstacle_height_m)
        candidates = np.column_stack([leveled[obstacle_mask], intensity[obstacle_mask]])
        if candidates.shape[0] == 0:
            return candidates

        # 3b) Filtr "rozmazanej glebokosci" (depth-smeared ray) - odsiewa
        # fantomowe zwroty odrozniajace sie geometrycznie od realnych
        # obiektow. Zmierzone empirycznie na zywym robocie w POTWIERDZONYM
        # pustym pomieszczeniu: w waskim (2-stopniowym) sektorze kierunku,
        # realny obiekt zajmowal 1-2 przedzialy zasiegu 0.5m (rozpietosc
        # ~0.4m), podczas gdy fantomowe sektory zajmowaly 12-14 przedzialow
        # (rozpietosc 6-7.5m) - sygnatura rozpraszania wewnatrz jednego
        # kierunku (podejrzenie: zabrudzona/zarysowana szybka ochronna albo
        # czesciowa przeslona z tej strony), nie realna geometria (zaden
        # realny obiekt nie zwraca echa rownoczesnie na kazdym dystansie w
        # jednym kierunku). Patrz docstring _filter_depth_smeared_rays -
        # zliczanie ZAJETYCH BINOW (nie przerw miedzy punktami) jest
        # kluczowe, zeby dzialalo niezaleznie od gestosci punktow. W
        # sektorach z >=4 zajetymi binami zostaje TYLKO najblizsza spojna
        # grupa - bezpieczne dla unikania kolizji (najblizsza przeszkoda
        # zawsze przechodzi), odrzucane sa jedynie dalsze, podejrzane
        # zwroty. Sektory z <4 binami (typowa scena: sciana + mebel przed
        # nia) NIE sa ruszane.
        candidates = _filter_depth_smeared_rays(candidates)
        if candidates.shape[0] == 0:
            return candidates

        # 4) Deduplikacja siatka wokselowa - jeden REALNY punkt na kostke
        # (najblizszy centroidowi kostki), nie interpolowana srednia.
        # (dziala na x,y,z; intensity przechodzi razem z wybranym punktem).
        reduced = self._voxel_downsample(candidates)

        # 5) Twardy limit liczby punktow - PROPORCJONALNIE wg odleglosci
        # (nie samo "najblizsze"), bo gestosc lidaru mocno rosnie blisko
        # robota (np. stol/podloga tuz pod czujnikiem) i przy czystym
        # priorytecie najblizszych potrafila calkowicie zdominowac budzet,
        # usuwajac dalekie sciany/przeszkody z wyniku.
        if reduced.shape[0] > self.max_output_points:
            reduced = self._select_evenly_by_distance(reduced)

        return reduced

    def _select_evenly_by_distance(self, pts: np.ndarray) -> np.ndarray:
        """
        Dzieli punkty na przedzialy odleglosci (XY) i probkuje z kazdego
        przedzialu w miare rownej liczbie (max_output_points // n_bins) -
        dalekie punkty (ktorych jest mniej z natury gestosci lidaru) nie
        zostaja zdominowane/wyparte przez bliska chmure. Niewykorzystany
        budzet z ubogich przedzialow (za malo punktow, zeby zapelnic
        wlasna kwote) jest dolozony do najblizszych pozostalych punktow,
        zeby w pelni wykorzystac max_output_points.
        """
        n = pts.shape[0]
        dist = np.sqrt(pts[:, 0] ** 2 + pts[:, 1] ** 2)

        n_bins = max(1, min(20, self.max_output_points // 10))
        bin_edges = np.linspace(0.0, float(dist.max()) + 1e-6, n_bins + 1)
        bin_idx = np.clip(np.digitize(dist, bin_edges) - 1, 0, n_bins - 1)

        quota_per_bin = self.max_output_points // n_bins
        selected_parts = []

        for b in range(n_bins):
            idx_in_bin = np.flatnonzero(bin_idx == b)
            take = min(idx_in_bin.shape[0], quota_per_bin)
            if take == 0:
                continue
            if take < idx_in_bin.shape[0]:
                # Rownomierny (co-N-ty), deterministyczny wybor w obrebie
                # przedzialu - nie faworyzuje zadnego konca przedzialu.
                stride = idx_in_bin.shape[0] / take
                pick = (np.arange(take) * stride).astype(np.int64)
                chosen = idx_in_bin[pick]
            else:
                chosen = idx_in_bin
            selected_parts.append(chosen)

        selected = (
            np.concatenate(selected_parts) if selected_parts else np.empty(0, dtype=np.int64)
        )

        # Redystrybucja niewykorzystanego budzetu (przedzialy zbyt ubogie,
        # zeby zapelnic wlasna kwote) - dobieramy najblizsze z pozostalych
        # punktow, zeby faktycznie wykorzystac caly max_output_points.
        remaining_budget = self.max_output_points - selected.shape[0]
        if remaining_budget > 0 and selected.shape[0] < n:
            remaining_mask = np.ones(n, dtype=bool)
            remaining_mask[selected] = False
            remaining_idx = np.flatnonzero(remaining_mask)
            extra_needed = min(remaining_budget, remaining_idx.shape[0])
            if extra_needed > 0:
                remaining_dist_sq = dist[remaining_idx] ** 2
                if extra_needed < remaining_idx.shape[0]:
                    extra_pick = np.argpartition(remaining_dist_sq, extra_needed - 1)[:extra_needed]
                    extra_idx = remaining_idx[extra_pick]
                else:
                    extra_idx = remaining_idx
                selected = np.concatenate([selected, extra_idx])

        return pts[selected]

    def _voxel_downsample(self, pts: np.ndarray) -> np.ndarray:
        """
        pts: (N,3) lub (N,4) - wokselizacja dziala TYLKO na x,y,z (pierwsze
        3 kolumny); ewentualna 4. kolumna (intensity) przechodzi razem z
        wybranym reprezentatywnym punktem, ale nie wplywa na wybor wokseli.
        """
        xyz = pts[:, :3]
        voxel_idx = np.floor(xyz / self.voxel_size_m).astype(np.int32)

        _, inverse, counts = np.unique(voxel_idx, axis=0, return_inverse=True, return_counts=True)
        n_voxels = counts.shape[0]

        centroid = np.zeros((n_voxels, 3), dtype=np.float64)
        np.add.at(centroid, inverse, xyz)
        centroid /= counts[:, None]

        diff = xyz - centroid[inverse]
        dist_to_centroid = np.einsum("ij,ij->i", diff, diff)

        order = np.lexsort((dist_to_centroid, inverse))
        sorted_inverse = inverse[order]
        _, first_positions = np.unique(sorted_inverse, return_index=True)
        chosen_indices = order[first_positions]

        return pts[chosen_indices]
