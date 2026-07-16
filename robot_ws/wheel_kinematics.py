"""
Kinematyka mecanum: przeliczenie predkosci 4 kol (rad/s) na predkosc ciala
robota (vx, vy, wz) w ukladzie lokalnym robota, oraz dekodowanie surowych
wartosci PWM (para kanalow: przod/tyl per kolo) na znormalizowana predkosc.

Geometria zmierzona fizycznie na robocie:
- srednica kola: 48 mm -> promien 0.024 m
- rozstaw lewo-prawo (miedzy kolami lewymi i prawymi): 17 cm -> polowa 0.085 m
- rozstaw przod-tyl (wheelbase): 16 cm -> polowa 0.08 m

Mapowanie kanalow PWM (sterownik PCA9685, kanaly 0-15, kazdy kanal 0-4095):
kazde kolo ma DWA kanaly - jeden dla obrotu do przodu, drugi do tylu.
    FL (przod-lewo):  kanal 0 = przod, kanal 1 = tyl
    RL (tyl-lewo):    kanal 2 = przod, kanal 3 = tyl
    FR (przod-prawo): kanal 5 = przod, kanal 4 = tyl
    RR (tyl-prawo):   kanal 7 = przod, kanal 6 = tyl
"""

WHEEL_RADIUS_M = 0.024
HALF_TRACK_M = 0.085       # polowa rozstawu lewo-prawo
HALF_WHEELBASE_M = 0.08    # polowa rozstawu przod-tyl
PWM_MAX = 4095

WHEEL_CHANNELS = {
    "FL": (0, 1),
    "RL": (2, 3),
    "FR": (5, 4),
    "RR": (7, 6),
}


def pwm_pair_to_signed_fraction(forward_raw: int, backward_raw: int, pwm_max: int = PWM_MAX) -> float:
    """Para surowych wartosci PWM (0-pwm_max) danego kola -> znormalizowana
    predkosc w zakresie [-1, 1] (dodatnia = do przodu)."""
    forward_frac = max(0, min(pwm_max, forward_raw)) / pwm_max
    backward_frac = max(0, min(pwm_max, backward_raw)) / pwm_max
    return forward_frac - backward_frac


def wheel_speeds_to_body_velocity(
    w_fl: float, w_fr: float, w_rl: float, w_rr: float,
    wheel_radius_m: float = WHEEL_RADIUS_M,
    half_wheelbase_m: float = HALF_WHEELBASE_M,
    half_track_m: float = HALF_TRACK_M,
) -> tuple[float, float, float]:
    """Predkosci katowe 4 kol (rad/s, dodatnia = do przodu) -> predkosc
    ciala robota (vx, vy, wz) w ukladzie lokalnym: vx,vy w m/s, wz w rad/s.
    Standardowa (pseudo-odwrotnosc Jakobianu) kinematyka mecanum.

    Podnosi ValueError przy zdegenerowanej geometrii (promien kola = 0,
    albo suma polowy rozstawu przod-tyl i lewo-prawo = 0) - to bledna
    konfiguracja, nie realny stan robota, wiec failujemy szybko i czytelnie
    zamiast po cichu dzielic przez zero."""
    if wheel_radius_m <= 0:
        raise ValueError(f"wheel_radius_m musi byc dodatnie, otrzymano {wheel_radius_m}")
    if half_wheelbase_m + half_track_m <= 0:
        raise ValueError(
            f"half_wheelbase_m + half_track_m musi byc dodatnie, otrzymano {half_wheelbase_m + half_track_m}"
        )

    r = wheel_radius_m
    k = half_wheelbase_m + half_track_m
    vx = (r / 4.0) * (w_fl + w_fr + w_rl + w_rr)
    vy = (r / 4.0) * (-w_fl + w_fr + w_rl - w_rr)
    wz = (r / (4.0 * k)) * (-w_fl + w_fr - w_rl + w_rr)
    return vx, vy, wz
