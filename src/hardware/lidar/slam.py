"""
Wrapper BreezySLAM (CoreSLAM/RMHC) dla lidara 3D (Unitree L2) w projekcie
Gremlin. Punkty 3D w poziomym ukladzie robota (po korekcie pochylenia
montazu i ground removal - patrz LidarObstacleReducer) sa rzutowane na
plaszczyzne X/Y i podawane do BreezySLAM jako pary (odleglosc_mm, kat_st),
bez budowania regularnej siatki katowej - dokladnie ten wzorzec, ktory
biblioteka sama stosuje w oficjalnym przykladzie rpslam.py dla RPLidar.

WAZNE - zweryfikowane empirycznie (patrz historia zmian):
- BreezySLAM NIE jest dostepny na PyPI. Trzeba go zbudowac ze zrodel:
  git clone https://github.com/simondlevy/BreezySLAM.git
  cd BreezySLAM/python && python setup.py build_ext --inplace
  a nastepnie skopiowac pybreezyslam*.so oraz katalog breezyslam/ do
  site-packages venv. Patrz install_breezyslam.sh w tym samym katalogu.
- Konwencja katow: w lokalnej ramce skanu BreezySLAM kat 0 st. = "wprost
  do przodu" (lokalne +X'), a +Y' = lewo robota (patrz c/coreslam.c:
  x=dist*cos(kat), y=dist*sin(kat) przy kat=0 -> x=dist,y=0). W naszym
  projekcie x=prawo, y=przod, wiec X'=y, Y'=-x - std minus przy x w
  update() ponizej. Pomylenie tego znaku daje pozornie "dzialajacy" kod,
  ktory w praniu produkuje katastrofalny dryf rotacji (sprawdzone).
- RMHC to algorytm hillclimbing z pojedyncza hipoteza pozycji (nie filtr
  czastek/EKF) - w SYMETRYCZNYCH/ubogich w cechy pomieszczeniach (np.
  idealnie kwadratowy pokoj bez mebli) potrafi pogubic orientacje mimo
  poprawnej odometrii, bo dopasowanie skanu do mapy jest niejednoznaczne.
  W testach na syntetycznym kwadratowym pokoju (najgorszy mozliwy
  przypadek) blad rotacji siegal kilkudziesieciu stopni nawet z
  odometria. Realne pomieszczenia (meble, drzwi, niesymetryczne sciany)
  daja znacznie wiecej sygnalu korelacyjnego - PRZED zaufaniem pozycji
  z tego modulu na prawdziwym robocie nalezy to zweryfikowac na
  rzeczywistych danych z L2, nie tylko na symulacji.
- Wydajnosc na Raspberry Pi 5 jest OK: ~4-6 ms/update przy ~200 pkt/skan
  (zmierzone), a wiec >150 Hz teoretycznego tempa - nie jest waskim
  gardlem. Problemem jest dokladnosc/stabilnosc RMHC w ubogich scenach,
  nie wydajnosc.
- Silnie zalecane: podawac pose_change z odometrii kol (encoder_worker.py
  juz istnieje w projekcie) - bez tego (czyste dopasowanie skanu) dryf
  jest jeszcze wiekszy. Z odometria warto tez zaciasnic sigma_xy_mm/
  sigma_theta_degrees ponizej domyslnych (100mm/20st), bo enkodery daja
  juz dobry prior i RMHC ma tylko korygowac mala reszte bledu - ale
  dobierz te wartosci empirycznie na prawdziwych danych, nie w ciemno.
"""

import math
from typing import List, Optional, Tuple

from breezyslam.algorithms import RMHC_SLAM
from breezyslam.sensors import Laser


class LidarSlam:
    def __init__(
        self,
        map_size_pixels: int = 500,
        map_size_meters: float = 10.0,
        max_range_mm: float = 8000.0,
        max_points_per_scan: int = 500,
        map_quality: int = 50,
        hole_width_mm: float = 200.0,
        sigma_xy_mm: float = 100.0,
        sigma_theta_degrees: float = 20.0,
        random_seed: Optional[int] = None,
    ):
        self.max_points_per_scan = max_points_per_scan

        laser = Laser(
            scan_size=max_points_per_scan,
            scan_rate_hz=10.0,
            detection_angle_degrees=360.0,
            distance_no_detection_mm=max_range_mm,
        )
        self._slam = RMHC_SLAM(
            laser,
            map_size_pixels,
            map_size_meters,
            map_quality=map_quality,
            hole_width_mm=hole_width_mm,
            sigma_xy_mm=sigma_xy_mm,
            sigma_theta_degrees=sigma_theta_degrees,
            random_seed=random_seed,
        )
        self._map_size_pixels = map_size_pixels

    def update(
        self,
        points_xy_m: List[Tuple[float, float]],
        pose_change_mm_deg_s: Optional[Tuple[float, float, float]] = None,
    ) -> Tuple[float, float, float]:
        """
        points_xy_m: (x, y) w metrach w poziomym ukladzie robota (x=prawo,
        y=przod), juz po korekcie pochylenia lidara i ground removal
        (np. wynik LidarObstacleReducer.reduce()[:, :2]).
        pose_change_mm_deg_s: opcjonalna odometria (dxy_mm, dtheta_deg,
        dt_s) z enkoderow kol - bez niej SLAM szuka pozycji czysto ze
        skanu (odometry-free), co jest mniej stabilne (patrz uwagi w
        naglowku pliku).
        Zwraca (x_mm, y_mm, theta_deg) - biezaca estymowana pozycja robota.
        """
        distances_mm = []
        angles_deg = []
        for x, y in points_xy_m[: self.max_points_per_scan]:
            distance_mm = math.hypot(x, y) * 1000.0
            if distance_mm <= 0.0:
                continue
            # BreezySLAM: lokalny kat 0 = "wprost do przodu" (lokalne +X'),
            # +Y' = lewo robota. U nas x=prawo, y=przod, wiec X'=y, Y'=-x.
            angle_deg = math.degrees(math.atan2(-x, y))
            distances_mm.append(distance_mm)
            angles_deg.append(angle_deg)

        if not distances_mm:
            return self._slam.getpos()

        self._slam.update(
            distances_mm,
            pose_change=pose_change_mm_deg_s,
            scan_angles_degrees=angles_deg,
        )
        return self._slam.getpos()

    def get_map(self) -> bytearray:
        mapbytes = bytearray(self._map_size_pixels * self._map_size_pixels)
        self._slam.getmap(mapbytes)
        return mapbytes
