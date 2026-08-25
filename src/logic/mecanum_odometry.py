"""
Kinematyka odwrotna (forward kinematics) napedu mecanum: przeksztalca
przyrosty tickow enkoderow 4 kol (FL, FR, RL, RR) na przemieszczenie
robota (vx=przod, vy=w bok, omega=obrot).

KALIBRACJA - PRZECZYTAJ PRZED UZYCIEM:
Znamy tylko srednice kola (48 mm). Trzy pozostale stale sa PLACEHOLDERAMI
(oznaczone TODO_KALIBRACJA w config.json -> "drivetrain") i NIE zostaly
zmierzone/zweryfikowane na prawdziwym robocie:

  1. ticks_per_revolution - ile tickow enkodera przypada na 1 pelny obrot
     kola. Kalibracja: obroc kolo recznie dokladnie N pelnych obrotow
     (np. N=10, oznacz punkt startowy taśma), odczytaj delte tickow z
     `get_encoder_ticks` (WS) albo `EncoderController.get_ticks(nazwa)`,
     podziel przez N.

  2. wheelbase_mm i track_width_mm - odleglosc (mm) miedzy srodkami kol
     odpowiednio przod-tyl i lewo-prawo. Najlatwiej po prostu zmierzyc
     linijka/tasma - nie wymaga zadnego ruchu robota.

  3. encoder_sign per kolo (domyslnie wszystkie +1) - enkodery moga byc
     fizycznie podlaczone tak, ze dodatnie ticki nie odpowiadaja kierunkowi
     "kolo kreci sie do przodu" zgodnemu z konwencja PWM z control.js.
     Kalibracja: wyslij komende "Przod" na krotki, stary czas przy niskim
     PWM, sprawdz czy WSZYSTKIE 4 kola pokazuja ticki o tym samym znaku
     i zblizonej wartosci bezwzglednej. Jesli ktores ma odwrotny znak,
     ustaw jego encoder_sign na -1 w configu.

  4. Sprawdzenie koncowe: wyslij "Full lewo"/"Full prawo" (czysty ruch w
     bok) na krotki czas - jesli geometria/znaki sa poprawne, estymowany
     kierunek ruchu z compute_pose_change powinien byc w przyblizeniu
     boczny, a nie do przodu/w tyl.

Dopoki te wartosci nie zostana skalibrowane, pose_change z tego modulu
jest tylko PRZYBLIZONYM priorem dla SLAM - lepszym niz brak odometrii
(patrz testy w hardware/lidar/slam.py), ale nie dokladnym pomiarem.

WAZNE OGRANICZENIE BreezySLAM: RMHC_SLAM.update() przyjmuje pose_change
jako (dxy_mm, dtheta_deg, dt_s) - SKALARNY dystans "do przodu" + obrot,
bez skladowej bocznej (patrz breezyslam/algorithms.py:
SinglePositionSLAM._updateMapAndPointcloud). To jest model nieholonomiczny
(rozniczkowy) - NIE obsluguje strafe'u wprost. Nasz robot (mecanum) MOZE
sie poruszac bokiem, ale taki ruch nie da sie w pelni przekazac do
BreezySLAM - compute_pose_change() zwraca wiec tylko skladowa "do przodu"
(vx) i obrot (omega), a skladowa boczna (vy) jest pomijana. Podczas
czystego strafe'u odometria przekazywana do SLAM bedzie wiec niedokladna
(zaniza dystans) - to ograniczenie biblioteki, nie bledu w tym module.
"""

import math
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class MecanumGeometry:
    wheel_diameter_mm: float = 48.0
    ticks_per_revolution: int = 560  # TODO_KALIBRACJA - patrz naglowek pliku
    wheelbase_mm: float = 160.0      # TODO_KALIBRACJA - zmierz linijka
    track_width_mm: float = 160.0    # TODO_KALIBRACJA - zmierz linijka
    encoder_sign: Dict[str, int] = field(
        default_factory=lambda: {"FL": 1, "FR": 1, "RL": 1, "RR": 1}
    )


class MecanumOdometry:
    """
    Utrzymuje ostatni odczyt tickow 4 kol i na podstawie kolejnych
    odczytow liczy przemieszczenie robota (standardowa kinematyka mecanum,
    konfiguracja X-kol).
    """

    def __init__(self, geometry: MecanumGeometry):
        self.geometry = geometry
        self.mm_per_tick = (
            math.pi * geometry.wheel_diameter_mm / geometry.ticks_per_revolution
        )
        self._half_wheelbase_mm = geometry.wheelbase_mm / 2.0
        self._half_track_mm = geometry.track_width_mm / 2.0
        self._lx_plus_ly = self._half_wheelbase_mm + self._half_track_mm

        self._prev_ticks: Dict[str, int] | None = None

    def reset(self, ticks: Dict[str, int]) -> None:
        """Ustawia punkt odniesienia bez liczenia przemieszczenia (np. przy starcie)."""
        self._prev_ticks = dict(ticks)

    def compute_pose_change(
        self, ticks: Dict[str, int], dt_s: float
    ) -> tuple[float, float, float] | None:
        """
        ticks: aktualne (skumulowane) odczyty z EncoderController.get_all_ticks()
        dt_s: czas od poprzedniego wywolania (sekundy)

        Zwraca (dxy_mm, dtheta_deg, dt_s) w formacie oczekiwanym przez
        BreezySLAM (RMHC_SLAM.update(pose_change=...)), albo None przy
        pierwszym wywolaniu (brak punktu odniesienia).
        """
        if self._prev_ticks is None or dt_s <= 0:
            self.reset(ticks)
            return None

        deltas = {}
        for name in ("FL", "FR", "RL", "RR"):
            sign = self.geometry.encoder_sign.get(name, 1)
            delta_ticks = ticks.get(name, 0) - self._prev_ticks.get(name, 0)
            deltas[name] = sign * delta_ticks

        self._prev_ticks = dict(ticks)

        # Predkosc liniowa (mm/s) kazdego kola z przyrostu tickow.
        wheel_mm_s = {name: (deltas[name] * self.mm_per_tick) / dt_s for name in deltas}

        # Standardowa kinematyka mecanum (konfiguracja X, kola numerowane
        # FL/FR/RL/RR) - patrz np. "Mecanum wheel robot" literatura
        # robotyczna. R juz wliczone w wheel_mm_s (to predkosc liniowa
        # obwodu kola, nie katowa).
        vx = (wheel_mm_s["FL"] + wheel_mm_s["FR"] + wheel_mm_s["RL"] + wheel_mm_s["RR"]) / 4.0
        vy = (-wheel_mm_s["FL"] + wheel_mm_s["FR"] + wheel_mm_s["RL"] - wheel_mm_s["RR"]) / 4.0
        omega_rad_s = (
            (-wheel_mm_s["FL"] + wheel_mm_s["FR"] - wheel_mm_s["RL"] + wheel_mm_s["RR"])
            / (4.0 * self._lx_plus_ly)
        )

        # BreezySLAM pose_change nie obsluguje skladowej bocznej (patrz
        # naglowek pliku) - przekazujemy tylko skladowa "do przodu" (vx)
        # i obrot. vy jest tu celowo pomijane, nie przez pomylke.
        dxy_mm = vx * dt_s
        dtheta_deg = math.degrees(omega_rad_s) * dt_s

        return (dxy_mm, dtheta_deg, dt_s)
