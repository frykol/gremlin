# Lidar SLAM z odometrią kołową — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dać ICP w `lidar_slam.py` sensowny initial guess z prędkości kół (zamiast zgadywania "brak ruchu"), żeby scan-matching nie rozjeżdżał się przy realnym ruchu robota.

**Architecture:** Dwa niezależne procesy komunikujące się przez plik stanu: `robot_controller` (gremlin/src, asyncio) okresowo zapisuje stan kanałów PWM napędu kół do `/tmp/wheel_state.json`; `lidar_slam.py` (robot_ws, standalone) odczytuje ten plik, liczy prędkość ciała robota modelem kinematyki mecanum, całkuje ją w przyrostową transformację SE(2) i podaje jako initial guess dla ICP. Brak pliku/nieaktualny plik → fallback do dzisiejszego zachowania (zero-motion).

**Tech Stack:** Python 3.13, numpy, scipy (cKDTree), pytest. Dwa oddzielne środowiska: `~/gremlin/.venv` (kod robot_controller/command_processor, ma smbus2/gpiod) i `~/lidar_venv` (kod robot_ws, ma pyserial/scipy).

## Global Constraints

- Geometria fizyczna robota (zmierzona): promień koła 0.024 m, rozstaw lewo-prawo 0.17 m (połowa: 0.085 m), rozstaw przód-tył (wheelbase) 0.16 m (połowa: 0.08 m).
- Mapowanie kanałów PWM (sterownik PCA9685, kanały 0-15, każdy 0-4095): FL: kanał 0=przód/1=tył; RL: kanał 2=przód/3=tył; FR: kanał 5=przód/4=tył; RR: kanał 7=przód/6=tył.
- Brak enkoderów/czujników prędkości — jedyna kalibracja to ręczny pomiar fizyczny (Task 5).
- Świadomie poza zakresem: loop closure, fuzja EKF (patrz spec, sekcja "Poza zakresem").
- Nowe pliki w `robot_ws/` są płaskie (bez `__init__.py`, bez pakietu) — importy działają przez uruchamianie skryptów z katalogu `robot_ws/` (ten sam wzorzec co istniejące `from lidar_live_capture import ...` w `lidar_slam.py`).

---

## Task 1: `wheel_kinematics.py` — kinematyka mecanum i dekodowanie PWM

**Files:**
- Create: `robot_ws/wheel_kinematics.py`
- Test: `robot_ws/test_wheel_kinematics.py`

**Interfaces:**
- Produces: `WHEEL_CHANNELS: dict[str, tuple[int,int]]` (mapowanie koło → (kanał_przód, kanał_tył)), `WHEEL_RADIUS_M: float`, `HALF_TRACK_M: float`, `HALF_WHEELBASE_M: float`, `PWM_MAX: int`, `pwm_pair_to_signed_fraction(forward_raw: int, backward_raw: int, pwm_max: int = PWM_MAX) -> float`, `wheel_speeds_to_body_velocity(w_fl: float, w_fr: float, w_rl: float, w_rr: float, wheel_radius_m: float = WHEEL_RADIUS_M, half_wheelbase_m: float = HALF_WHEELBASE_M, half_track_m: float = HALF_TRACK_M) -> tuple[float,float,float]` (zwraca `vx, vy, wz`).

- [ ] **Step 1: Zainstaluj pytest w lidar_venv**

Run: `~/lidar_venv/bin/pip install pytest`
Expected: `Successfully installed pytest-...`

- [ ] **Step 2: Napisz failing testy**

Utwórz `robot_ws/test_wheel_kinematics.py`:

```python
import pytest

from wheel_kinematics import pwm_pair_to_signed_fraction, wheel_speeds_to_body_velocity


def test_pwm_pair_full_forward():
    assert pwm_pair_to_signed_fraction(4095, 0, pwm_max=4095) == pytest.approx(1.0)


def test_pwm_pair_full_backward():
    assert pwm_pair_to_signed_fraction(0, 4095, pwm_max=4095) == pytest.approx(-1.0)


def test_pwm_pair_stopped():
    assert pwm_pair_to_signed_fraction(0, 0, pwm_max=4095) == pytest.approx(0.0)


def test_pwm_pair_half_forward():
    assert pwm_pair_to_signed_fraction(2048, 0, pwm_max=4095) == pytest.approx(2048 / 4095)


def test_wheel_speeds_pure_forward():
    # r=1, half_wheelbase=1, half_track=1: wszystkie kola ta sama predkosc
    vx, vy, wz = wheel_speeds_to_body_velocity(
        w_fl=2.0, w_fr=2.0, w_rl=2.0, w_rr=2.0,
        wheel_radius_m=1.0, half_wheelbase_m=1.0, half_track_m=1.0,
    )
    assert vx == pytest.approx(2.0)
    assert vy == pytest.approx(0.0)
    assert wz == pytest.approx(0.0)


def test_wheel_speeds_pure_rotation():
    vx, vy, wz = wheel_speeds_to_body_velocity(
        w_fl=-2.0, w_fr=2.0, w_rl=-2.0, w_rr=2.0,
        wheel_radius_m=1.0, half_wheelbase_m=1.0, half_track_m=1.0,
    )
    assert vx == pytest.approx(0.0)
    assert vy == pytest.approx(0.0)
    assert wz == pytest.approx(1.0)


def test_wheel_speeds_pure_strafe():
    vx, vy, wz = wheel_speeds_to_body_velocity(
        w_fl=-2.0, w_fr=2.0, w_rl=2.0, w_rr=-2.0,
        wheel_radius_m=1.0, half_wheelbase_m=1.0, half_track_m=1.0,
    )
    assert vx == pytest.approx(0.0)
    assert vy == pytest.approx(2.0)
    assert wz == pytest.approx(0.0)


def test_wheel_speeds_uses_physical_defaults():
    # Sanity check ze domyslne stale to fizyczna geometria robota, nie
    # wartosci testowe r=1 z powyzszych testow.
    vx, vy, wz = wheel_speeds_to_body_velocity(w_fl=10.0, w_fr=10.0, w_rl=10.0, w_rr=10.0)
    assert vx == pytest.approx(0.024 * 10.0)


def test_wheel_speeds_rejects_zero_wheel_radius():
    with pytest.raises(ValueError, match="wheel_radius_m"):
        wheel_speeds_to_body_velocity(
            w_fl=1.0, w_fr=1.0, w_rl=1.0, w_rr=1.0,
            wheel_radius_m=0.0, half_wheelbase_m=1.0, half_track_m=1.0,
        )


def test_wheel_speeds_rejects_zero_geometry_sum():
    with pytest.raises(ValueError, match="half_wheelbase_m \\+ half_track_m"):
        wheel_speeds_to_body_velocity(
            w_fl=1.0, w_fr=1.0, w_rl=1.0, w_rr=1.0,
            wheel_radius_m=1.0, half_wheelbase_m=0.0, half_track_m=0.0,
        )
```

- [ ] **Step 3: Uruchom testy, sprawdź że failują (moduł jeszcze nie istnieje)**

Run: `cd ~/gremlin/robot_ws && ~/lidar_venv/bin/python -m pytest test_wheel_kinematics.py -v`
Expected: `ModuleNotFoundError: No module named 'wheel_kinematics'`

- [ ] **Step 4: Napisz implementację**

Utwórz `robot_ws/wheel_kinematics.py`:

```python
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
```

- [ ] **Step 5: Uruchom testy, sprawdź że przechodzą**

Run: `cd ~/gremlin/robot_ws && ~/lidar_venv/bin/python -m pytest test_wheel_kinematics.py -v`
Expected: `10 passed`

- [ ] **Step 6: Commit**

```bash
cd ~/gremlin
git add robot_ws/wheel_kinematics.py robot_ws/test_wheel_kinematics.py
git commit -m "feat: add mecanum wheel kinematics module for lidar SLAM odometry"
```

---

## Task 2: `CommandProcessor` — śledzenie i zapis stanu kanałów PWM kół

**Files:**
- Modify: `gremlin/src/services/command_processor.py`
- Modify: `gremlin/src/robot_controller.py:91-96`
- Test: `gremlin/tests/test_command_processor.py`

**Interfaces:**
- Consumes: nic nowego (istniejące `CommandProcessor.__init__`, `process_commands`)
- Produces: `CommandProcessor.wheel_channel_state: dict[int, int]`, `CommandProcessor.write_wheel_state(path: str = WHEEL_STATE_PATH) -> None`, `CommandProcessor.run_wheel_state_writer(path: str = WHEEL_STATE_PATH, interval: float = 0.075) -> None` (coroutine, pętla nieskończona), moduł-level `WHEEL_STATE_PATH = "/tmp/wheel_state.json"`.

- [ ] **Step 1: Napisz failing testy**

Dopisz na końcu `gremlin/tests/test_command_processor.py`:

```python
import json


def test_motor_command_updates_wheel_channel_state():
    async def run_test():
        queue = asyncio.Queue()
        processor = CommandProcessor(
            command_queue=queue,
            gpio=DummyGpio(),
            i2c_pwm=DummyI2cPwm(),
            state=RobotState(),
            ws=DummyWs(),
            udp_frame_sender=DummyUdpFrameSender(),
        )

        queue.put_nowait({"type": "motor", "channel": 3, "pwm": 1500})
        await processor.process_commands()

        assert processor.wheel_channel_state == {3: 1500}

    asyncio.run(run_test())


def test_write_wheel_state_writes_atomic_json(tmp_path):
    processor = CommandProcessor(
        command_queue=asyncio.Queue(),
        gpio=DummyGpio(),
        i2c_pwm=DummyI2cPwm(),
        state=RobotState(),
        ws=DummyWs(),
        udp_frame_sender=DummyUdpFrameSender(),
    )
    processor.wheel_channel_state = {0: 4095, 1: 0, 2: 1500}

    out_path = tmp_path / "wheel_state.json"
    processor.write_wheel_state(str(out_path))

    assert out_path.exists()
    assert not (tmp_path / "wheel_state.json.tmp").exists()

    data = json.loads(out_path.read_text())
    assert data["channels"] == {"0": 4095, "1": 0, "2": 1500}
    assert isinstance(data["t_mono"], float)
```

- [ ] **Step 2: Uruchom testy, sprawdź że failują**

Run: `cd ~/gremlin && .venv/bin/python -m pytest tests/test_command_processor.py -v`
Expected: `AttributeError: 'CommandProcessor' object has no attribute 'wheel_channel_state'`

- [ ] **Step 3: Zmodyfikuj `command_processor.py`**

W `gremlin/src/services/command_processor.py` zamień linie 1-19 (importy i `__init__`) na:

```python
import base64
import json
import os
import asyncio
import time

from ..hardware.gpio.gpio_controller import GPIOController
from ..hardware.i2c.i2c_pwm import i2cPWM
from ..robot_state import RobotState
from ..dev_connection.interface import WSClientInterface

LOG_PATH = "sim.log"
WHEEL_STATE_PATH = "/tmp/wheel_state.json"

class CommandProcessor:
    def __init__(self, command_queue: asyncio.Queue, gpio: GPIOController, i2c_pwm: i2cPWM, state: RobotState, ws: WSClientInterface, udp_frame_sender):
        self.command_queue: asyncio.Queue = command_queue
        self.gpio: GPIOController = gpio
        self.i2c_pwm: i2cPWM = i2c_pwm
        self.state: RobotState = state
        self.ws: WSClientInterface = ws
        self.udp_frame_sender = udp_frame_sender
        self.wheel_channel_state: dict[int, int] = {}
```

Zamień linię 44-45 (`elif cmd.get("type") == "motor":` blok) na:

```python
                elif cmd.get("type") == "motor":
                    self.i2c_pwm.set_pwm(cmd["channel"], 0, cmd["pwm"])
                    self.wheel_channel_state[cmd["channel"]] = cmd["pwm"]
```

Dodaj po metodzie `_send_log` (na końcu klasy, po linii `}))`) dwie nowe metody:

```python
    def write_wheel_state(self, path: str = WHEEL_STATE_PATH) -> None:
        """Zapisuje aktualny stan kanalow PWM uzywanych do napedu kol wraz
        ze znacznikiem czasu monotonicznego, do odczytu przez
        wheel_odometry_reader.py (robot_ws) w osobnym procesie. Zapis
        atomowy (plik tymczasowy + rename), zeby czytelnik nigdy nie
        zobaczyl niekompletnego JSON-a."""
        payload = {
            "t_mono": time.monotonic(),
            "channels": {str(ch): pwm for ch, pwm in self.wheel_channel_state.items()},
        }
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w") as f:
            json.dump(payload, f)
        os.replace(tmp_path, path)

    async def run_wheel_state_writer(self, path: str = WHEEL_STATE_PATH, interval: float = 0.075):
        while True:
            self.write_wheel_state(path)
            await asyncio.sleep(interval)
```

- [ ] **Step 4: Uruchom testy, sprawdź że przechodzą**

Run: `cd ~/gremlin && .venv/bin/python -m pytest tests/test_command_processor.py -v`
Expected: `3 passed`

- [ ] **Step 5: Podłącz `run_wheel_state_writer` do listy tasków robota**

W `gremlin/src/robot_controller.py` zamień linie 91-96:

```python
        tasks = [
            asyncio.create_task(self.command_processor.run()),
            asyncio.create_task(self.camera_streamer.run()),
            asyncio.create_task(self.audio_streamer.run()),
            asyncio.create_task(self.logic.run()),
        ]
```

na:

```python
        tasks = [
            asyncio.create_task(self.command_processor.run()),
            asyncio.create_task(self.command_processor.run_wheel_state_writer()),
            asyncio.create_task(self.camera_streamer.run()),
            asyncio.create_task(self.audio_streamer.run()),
            asyncio.create_task(self.logic.run()),
        ]
```

- [ ] **Step 6: Uruchom cały zestaw testów gremlin, sprawdź że nic nie zepsuto**

Run: `cd ~/gremlin && .venv/bin/python -m pytest tests/ -v`
Expected: wszystkie testy `passed`

- [ ] **Step 7: Commit**

```bash
cd ~/gremlin
git add src/services/command_processor.py src/robot_controller.py tests/test_command_processor.py
git commit -m "feat: track and periodically persist wheel PWM channel state"
```

---

## Task 3: `wheel_odometry_reader.py` — odczyt stanu kół i całkowanie pozycji

**Files:**
- Create: `robot_ws/wheel_odometry_reader.py`
- Test: `robot_ws/test_wheel_odometry_reader.py`

**Interfaces:**
- Consumes: `wheel_kinematics.WHEEL_CHANNELS`, `wheel_kinematics.pwm_pair_to_signed_fraction`, `wheel_kinematics.wheel_speeds_to_body_velocity` (Task 1); plik JSON zapisywany przez `CommandProcessor.write_wheel_state()` (Task 2), format `{"t_mono": float, "channels": {"<kanal>": <pwm_raw>, ...}}`; `motor_driver.odometry.integrate_odometry(x, y, theta, vx, vy, wz, dt) -> (x, y, theta)` z `robot_ws/ros2_ws/src/motor_driver/motor_driver/odometry.py`.
- Produces: `WheelOdometryReader(state_path: str, max_wheel_speed_rad_s: float)` z metodą `poll_delta(max_age_s: float = 1.0) -> tuple[np.ndarray, np.ndarray] | None` (zwraca `(dR, dt)` — macierz obrotu 3x3 i wektor translacji 3-elementowy, przyrostowe względem poprzedniego wywołania; `None` gdy brak świeżych danych lub to pierwsze wywołanie).

- [ ] **Step 1: Napisz failing testy**

Utwórz `robot_ws/test_wheel_odometry_reader.py`:

```python
import json

import numpy as np
import pytest

from wheel_kinematics import WHEEL_CHANNELS
from wheel_odometry_reader import WheelOdometryReader


def write_state(path, t_mono, channels):
    path.write_text(json.dumps({"t_mono": t_mono, "channels": channels}))


def test_poll_delta_none_on_first_call(tmp_path):
    path = tmp_path / "wheel_state.json"
    write_state(path, t_mono=100.0, channels={})
    reader = WheelOdometryReader(str(path), max_wheel_speed_rad_s=10.0)

    assert reader.poll_delta(max_age_s=1e9) is None


def test_poll_delta_none_when_file_missing(tmp_path):
    path = tmp_path / "does_not_exist.json"
    reader = WheelOdometryReader(str(path), max_wheel_speed_rad_s=10.0)

    assert reader.poll_delta() is None


def test_poll_delta_none_when_stale(tmp_path):
    path = tmp_path / "wheel_state.json"
    write_state(path, t_mono=1.0, channels={})
    reader = WheelOdometryReader(str(path), max_wheel_speed_rad_s=10.0)

    assert reader.poll_delta(max_age_s=0.5) is None


def test_poll_delta_pure_forward_motion(tmp_path):
    path = tmp_path / "wheel_state.json"
    reader = WheelOdometryReader(str(path), max_wheel_speed_rad_s=10.0)

    all_forward_full = {}
    for fwd_ch, bwd_ch in WHEEL_CHANNELS.values():
        all_forward_full[str(fwd_ch)] = 4095
        all_forward_full[str(bwd_ch)] = 0

    write_state(path, t_mono=100.0, channels=all_forward_full)
    assert reader.poll_delta(max_age_s=1e9) is None  # pierwszy odczyt: brak dt do scalkowania

    write_state(path, t_mono=101.0, channels=all_forward_full)
    result = reader.poll_delta(max_age_s=1e9)

    assert result is not None
    dR, dt = result
    # domyslne r=0.024, pelna predkosc 10 rad/s na wszystkich kolach przez
    # 1s ruchu czysto do przodu -> dx = r * max_wheel_speed_rad_s * 1.0
    expected_dx = 0.024 * 10.0 * 1.0
    assert dt[0] == pytest.approx(expected_dx, rel=1e-6)
    assert dt[1] == pytest.approx(0.0, abs=1e-9)
    np.testing.assert_allclose(dR, np.eye(3), atol=1e-9)
```

- [ ] **Step 2: Uruchom testy, sprawdź że failują**

Run: `cd ~/gremlin/robot_ws && ~/lidar_venv/bin/python -m pytest test_wheel_odometry_reader.py -v`
Expected: `ModuleNotFoundError: No module named 'wheel_odometry_reader'`

- [ ] **Step 3: Napisz implementację**

Utwórz `robot_ws/wheel_odometry_reader.py`:

```python
"""
Odczyt stanu kol (zapisywanego przez CommandProcessor.write_wheel_state()
w gremlin/src) i przeliczenie go na przyrostowa transformacje SE(2) (dR
wokol osi Z, dt w plaszczyznie XY) do wykorzystania jako initial guess dla
ICP w lidar_slam.py.
"""
import json
import math
import os
import sys
import time

import numpy as np

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "ros2_ws", "src", "motor_driver"),
)
from motor_driver.odometry import integrate_odometry  # noqa: E402

from wheel_kinematics import (  # noqa: E402
    WHEEL_CHANNELS,
    pwm_pair_to_signed_fraction,
    wheel_speeds_to_body_velocity,
)


class WheelOdometryReader:
    def __init__(self, state_path: str, max_wheel_speed_rad_s: float):
        self.state_path = state_path
        self.max_wheel_speed_rad_s = max_wheel_speed_rad_s
        self._last_t_mono = None
        self._x = 0.0
        self._y = 0.0
        self._theta = 0.0

    def _read_state(self):
        try:
            with open(self.state_path) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def poll_delta(self, max_age_s: float = 1.0):
        """Zwraca (dR, dt) - przyrostowa transformacje SE(2) od ostatniego
        wywolania, albo None gdy brak swiezych danych o predkosciach kol
        (plik nieobecny/nieaktualny) lub to pierwsze wywolanie (nie ma
        jeszcze poprzedniego znacznika czasu do policzenia dt)."""
        data = self._read_state()
        if data is None:
            self._last_t_mono = None
            return None

        t_mono = data["t_mono"]
        if time.monotonic() - t_mono > max_age_s:
            self._last_t_mono = None
            return None

        if self._last_t_mono is None:
            self._last_t_mono = t_mono
            return None

        dt_elapsed = t_mono - self._last_t_mono
        self._last_t_mono = t_mono
        if dt_elapsed <= 0:
            return None

        channels = {int(k): v for k, v in data["channels"].items()}
        wheel_speeds = {}
        for name, (fwd_ch, bwd_ch) in WHEEL_CHANNELS.items():
            frac = pwm_pair_to_signed_fraction(
                channels.get(fwd_ch, 0), channels.get(bwd_ch, 0)
            )
            wheel_speeds[name] = frac * self.max_wheel_speed_rad_s

        vx, vy, wz = wheel_speeds_to_body_velocity(
            wheel_speeds["FL"], wheel_speeds["FR"],
            wheel_speeds["RL"], wheel_speeds["RR"],
        )

        x0, y0, theta0 = self._x, self._y, self._theta
        self._x, self._y, self._theta = integrate_odometry(
            self._x, self._y, self._theta, vx, vy, wz, dt_elapsed
        )

        dx = self._x - x0
        dy = self._y - y0
        dtheta = self._theta - theta0

        cos_t, sin_t = math.cos(dtheta), math.sin(dtheta)
        dR = np.array([
            [cos_t, -sin_t, 0.0],
            [sin_t, cos_t, 0.0],
            [0.0, 0.0, 1.0],
        ])
        dt = np.array([dx, dy, 0.0])
        return dR, dt
```

- [ ] **Step 4: Uruchom testy, sprawdź że przechodzą**

Run: `cd ~/gremlin/robot_ws && ~/lidar_venv/bin/python -m pytest test_wheel_odometry_reader.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
cd ~/gremlin
git add robot_ws/wheel_odometry_reader.py robot_ws/test_wheel_odometry_reader.py
git commit -m "feat: add wheel odometry reader integrating wheel state into SE(2) deltas"
```

---

## Task 4: `lidar_slam.py` — odometria kołowa jako initial guess dla ICP

**Files:**
- Modify: `robot_ws/lidar_slam.py`
- Test: `robot_ws/test_lidar_slam.py`

**Interfaces:**
- Consumes: `wheel_odometry_reader.WheelOdometryReader` (Task 3), jej `poll_delta() -> tuple[np.ndarray, np.ndarray] | None`.
- Produces: `LidarSlam.add_frame(frame_xyz, frame_intensity, t_stamp, odom_delta: tuple[np.ndarray, np.ndarray] | None = None) -> str` (zmieniona sygnatura — dodany opcjonalny `odom_delta`); CLI `--odom-state-file`, `--wheel-calibration`.

- [ ] **Step 1: Napisz failing testy**

Utwórz `robot_ws/test_lidar_slam.py`:

```python
import numpy as np

from lidar_slam import LidarSlam


def make_corner_cloud(n_per_face=200, seed=0):
    """Chmura punktow w ksztalcie naroznika (dwie prostopadle plaszczyzny)
    - w przeciwienstwie do pojedynczej plaskiej sciany daje ICP
    wystarczajaco cech geometrycznych do jednoznacznego dopasowania w obu
    osiach X i Y."""
    rng = np.random.default_rng(seed)
    face1 = np.column_stack([
        rng.uniform(-2, 2, n_per_face),
        np.zeros(n_per_face),
        rng.uniform(0, 2, n_per_face),
    ])
    face2 = np.column_stack([
        np.zeros(n_per_face),
        rng.uniform(-2, 2, n_per_face),
        rng.uniform(0, 2, n_per_face),
    ])
    return np.vstack([face1, face2])


def test_add_frame_converges_with_accurate_odom_guess():
    points = make_corner_cloud()
    intensity = np.full(len(points), 150.0)

    slam = LidarSlam(min_fitness=0.3, max_speed=100.0)
    status0 = slam.add_frame(points, intensity, t_stamp=0.0)
    assert status0 == "ok"

    true_translation = np.array([0.3, -0.15, 0.0])
    moved_points = points - true_translation  # w ukladzie czujnika po ruchu

    dR_odom = np.eye(3)
    dt_odom = true_translation.copy()
    status1 = slam.add_frame(
        moved_points, intensity, t_stamp=0.2, odom_delta=(dR_odom, dt_odom)
    )

    assert status1 == "ok"
    np.testing.assert_allclose(slam.pose_t, true_translation, atol=0.05)


def test_add_frame_rejects_when_odom_prediction_is_way_off():
    points = make_corner_cloud()
    intensity = np.full(len(points), 150.0)

    slam = LidarSlam(min_fitness=0.3, max_speed=100.0)
    slam.add_frame(points, intensity, t_stamp=0.0)

    true_translation = np.array([0.05, 0.0, 0.0])
    moved_points = points - true_translation

    # Odometria twierdzi ze robot pojechal 5m, mimo ze naprawde przesunal
    # sie o 5cm - powinno zostac odrzucone (fitness lub divergencja).
    dR_odom = np.eye(3)
    dt_odom = np.array([5.0, 0.0, 0.0])
    status = slam.add_frame(
        moved_points, intensity, t_stamp=0.2, odom_delta=(dR_odom, dt_odom)
    )

    assert status == "rejected"
    np.testing.assert_allclose(slam.pose_t, np.zeros(3))


def test_add_frame_without_odom_delta_keeps_zero_motion_fallback():
    points = make_corner_cloud()
    intensity = np.full(len(points), 150.0)

    slam = LidarSlam(min_fitness=0.3, max_speed=100.0)
    slam.add_frame(points, intensity, t_stamp=0.0)

    # Bez odom_delta - dokladnie ta sama chmura (brak ruchu) powinna zostac
    # zaakceptowana z pozycja bliska zeru (dzisiejsze zachowanie).
    status = slam.add_frame(points.copy(), intensity, t_stamp=0.2)

    assert status == "ok"
    np.testing.assert_allclose(slam.pose_t, np.zeros(3), atol=0.05)
```

- [ ] **Step 2: Uruchom testy, sprawdź że failują**

Run: `cd ~/gremlin/robot_ws && ~/lidar_venv/bin/python -m pytest test_lidar_slam.py -v`
Expected: `TypeError: add_frame() got an unexpected keyword argument 'odom_delta'`

- [ ] **Step 3: Zmodyfikuj `add_frame` w `lidar_slam.py`**

Zamień linie 117-158 (całą metodę `add_frame`) na:

```python
    def add_frame(self, frame_xyz, frame_intensity, t_stamp, odom_delta=None):
        if len(frame_xyz) < 30:
            return "too_small"  # zbyt maly fragment, pomijamy (szum/brak echa)

        if len(self.map_xyz) == 0 or not self.use_icp:
            # Pierwsza ramka definiuje poczatek ukladu globalnego, albo
            # SLAM dziala w trybie bez rejestracji (--no-icp).
            global_pts = (self.pose_R @ frame_xyz.T).T + self.pose_t
        else:
            if self._tree is None:
                self._rebuild_tree()

            if odom_delta is not None:
                dR_odom, dt_odom = odom_delta
                guess_R = dR_odom @ self.pose_R
                guess_t = dR_odom @ self.pose_t + dt_odom
            else:
                # Brak swiezych danych o ruchu z kol - zakladamy brak ruchu
                # wzgledem ostatniej pozy (jak dotychczas).
                guess_R = self.pose_R
                guess_t = self.pose_t

            guess = (guess_R @ frame_xyz.T).T + guess_t
            dR, dt, fitness = icp(guess, self._tree, self.map_xyz)

            new_pose_R = dR @ guess_R
            new_pose_t = dR @ guess_t + dt

            if odom_delta is not None:
                # Silniejszy sanity check niz sztywny limit predkosci:
                # porownaj wynik ICP z tym, co przewidziala odometria z
                # kol - wykrywa tez sytuacje gdy ICP "zjechal" w zle
                # lokalne minimum mimo wiarygodnej predkosci.
                odom_predicted_t = dR_odom @ self.pose_t + dt_odom
                divergence = float(np.linalg.norm(new_pose_t - odom_predicted_t))
                max_divergence = max(0.1, float(np.linalg.norm(dt_odom)) * 0.5 + 0.05)
                reject = fitness < self.min_fitness or divergence > max_divergence
            else:
                step_translation = float(np.linalg.norm(new_pose_t - self.pose_t))
                max_step = self.max_speed * self.frame_window
                reject = fitness < self.min_fitness or step_translation > max_step

            if reject:
                self.rejected_frames += 1
                self.trajectory.append((t_stamp, *self.pose_t.tolist()))
                return "rejected"

            self.pose_R = new_pose_R
            self.pose_t = new_pose_t
            global_pts = (self.pose_R @ frame_xyz.T).T + self.pose_t

        self.map_xyz = np.vstack([self.map_xyz, global_pts])
        self.map_intensity = np.concatenate([self.map_intensity, frame_intensity])

        if len(self.map_xyz) > self.map_cap:
            ds = voxel_downsample(
                np.hstack([self.map_xyz, self.map_intensity[:, None]]), self.voxel_size
            )
            self.map_xyz, self.map_intensity = ds[:, :3], ds[:, 3]

        self._rebuild_tree()
        self.trajectory.append((t_stamp, *self.pose_t.tolist()))
        return "ok"
```

- [ ] **Step 4: Uruchom testy, sprawdź że przechodzą**

Run: `cd ~/gremlin/robot_ws && ~/lidar_venv/bin/python -m pytest test_lidar_slam.py -v`
Expected: `3 passed`

- [ ] **Step 5: Podłącz odometrię do CLI i pętli głównej**

W `robot_ws/lidar_slam.py` dodaj do importów (po linii `import serial`):

```python
import json

from wheel_odometry_reader import WheelOdometryReader
```

Dodaj przed `def main():` nową funkcję:

```python
def load_wheel_calibration(path):
    with open(path) as f:
        data = json.load(f)
    return float(data["max_wheel_speed_rad_s"])
```

W `main()` dodaj po linii `ap.add_argument("--no-icp", ...)` (po jej zamykającym `)`) dwa nowe argumenty:

```python
    ap.add_argument(
        "--odom-state-file", default=None,
        help="sciezka do pliku stanu kol pisanego przez CommandProcessor.write_wheel_state() (np. /tmp/wheel_state.json) - gdy podane, ICP dostaje initial guess z odometrii kolowej zamiast zakladac brak ruchu",
    )
    ap.add_argument(
        "--wheel-calibration", default="wheel_calibration.json",
        help="plik JSON z zmierzona stala {'max_wheel_speed_rad_s': ...} - wymagany gdy podano --odom-state-file",
    )
```

Po linii `args = ap.parse_args()` dodaj:

```python

    odom_reader = None
    if args.odom_state_file:
        max_wheel_speed = load_wheel_calibration(args.wheel_calibration)
        odom_reader = WheelOdometryReader(args.odom_state_file, max_wheel_speed)
```

Zamień blok wywołania `slam.add_frame(...)` wewnątrz pętli głównej z:

```python
            if now - t_frame_start >= args.frame_window and frame_pts:
                slam.add_frame(
                    np.array(frame_pts, dtype=np.float64),
                    np.array(frame_int, dtype=np.float64),
                    now - t_start,
                )
```

na:

```python
            if now - t_frame_start >= args.frame_window and frame_pts:
                odom_delta = odom_reader.poll_delta() if odom_reader is not None else None
                slam.add_frame(
                    np.array(frame_pts, dtype=np.float64),
                    np.array(frame_int, dtype=np.float64),
                    now - t_start,
                    odom_delta=odom_delta,
                )
```

- [ ] **Step 6: Sprawdź że skrypt się importuje bez błędów (bez sprzętu)**

Run: `cd ~/gremlin/robot_ws && ~/lidar_venv/bin/python -c "import lidar_slam"`
Expected: brak błędów (pusty output)

- [ ] **Step 7: Uruchom pełny zestaw testów robot_ws**

Run: `cd ~/gremlin/robot_ws && ~/lidar_venv/bin/python -m pytest . -v`
Expected: wszystkie testy `passed` (z Task 1, 3 i 4 razem)

- [ ] **Step 8: Commit**

```bash
cd ~/gremlin
git add robot_ws/lidar_slam.py robot_ws/test_lidar_slam.py
git commit -m "feat: use wheel odometry as ICP initial guess in lidar_slam"
```

---

## Task 5: Fizyczna kalibracja prędkości koła

**Files:**
- Create: `robot_ws/calibrate_wheel_speed.py`

**Interfaces:**
- Produces: `robot_ws/wheel_calibration.json` z zawartością `{"max_wheel_speed_rad_s": <zmierzona liczba>}` — plik danych, nie kod; wymagany przez `lidar_slam.py --wheel-calibration` (Task 4).

- [ ] **Step 1: Napisz skrypt pomocniczy do fizycznej kalibracji**

Utwórz `robot_ws/calibrate_wheel_speed.py`:

```python
"""
Jednorazowy skrypt do fizycznej kalibracji predkosci kola: obraca wskazane
kolo przy 100% PWM przez zadany czas, zeby zmierzyc predkosc katowa
recznie (liczac obroty - nie ma enkoderow).

Uruchom z ~/gremlin/.venv (potrzebuje smbus2 i dostepu do magistrali I2C):
    cd ~/gremlin
    .venv/bin/python robot_ws/calibrate_wheel_speed.py --channel 0 --seconds 10

Podczas dzialania: policz ile pelnych obrotow wykonalo kolo w tym czasie
(np. oznacz punkt na oponie flamastrem i licz przejscia), potem wylicz:
    rad/s = (liczba_obrotow * 2 * pi) / seconds
i zapisz recznie wynik w robot_ws/wheel_calibration.json:
    {"max_wheel_speed_rad_s": <wynik>}

Powtorz dla kilku kol (np. kanal 0 = FL przod, kanal 5 = FR przod) i usrednij
wynik, jesli silniki roznia sie predkoscia.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.hardware.i2c.i2c_pwm import i2cPWM  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Kalibracja predkosci kola - obroc kolo przy 100% PWM")
    ap.add_argument("--channel", type=int, required=True, help="numer kanalu PWM (0-15) do obrotu")
    ap.add_argument("--seconds", type=float, default=10.0)
    args = ap.parse_args()

    pwm = i2cPWM()
    pwm.start()

    print(f"Kolo na kanale {args.channel} rusza na {args.seconds}s przy 100% PWM. Licz obroty!")
    pwm.set_pwm_percent(args.channel, 100.0)
    time.sleep(args.seconds)
    pwm.set_pwm_percent(args.channel, 0.0)
    print("Stop. Policz obroty i wylicz: rad/s = (obroty * 2*pi) / czas")
    print("Zapisz wynik w robot_ws/wheel_calibration.json jako {\"max_wheel_speed_rad_s\": <wynik>}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Wykonaj fizyczną kalibrację na robocie**

Podnieś robota tak, żeby koła obracały się swobodnie w powietrzu (nie dotykały podłoża — bezpieczeństwo i czystszy pomiar bez poślizgu). Oznacz punkt na jednym kole.

Run: `cd ~/gremlin && .venv/bin/python robot_ws/calibrate_wheel_speed.py --channel 0 --seconds 10`

Podczas 10 sekund policz liczbę pełnych obrotów koła (np. licząc przejścia oznaczonego punktu). Zapisz tę liczbę.

- [ ] **Step 3: Wylicz i zapisz stałą kalibracyjną**

Wylicz: `max_wheel_speed_rad_s = (policzone_obroty * 2 * 3.14159265) / 10.0`

Utwórz `robot_ws/wheel_calibration.json` z wynikiem, np.:

```json
{"max_wheel_speed_rad_s": 12.34}
```

(wartość `12.34` to placeholder w tym dokumencie planu — wpisz tam realny wynik pomiaru).

- [ ] **Step 4: Commit**

```bash
cd ~/gremlin
git add robot_ws/calibrate_wheel_speed.py robot_ws/wheel_calibration.json
git commit -m "chore: add wheel speed calibration script and measured constant"
```

---

## Task 6: Walidacja end-to-end na jeżdżącym robocie

**Files:** brak nowych plików — ten task to udokumentowana procedura ręczna.

**Interfaces:**
- Consumes: wszystko z Task 1-5 razem: `robot_controller` piszący `/tmp/wheel_state.json`, `lidar_slam.py --odom-state-file /tmp/wheel_state.json --wheel-calibration robot_ws/wheel_calibration.json`.

- [ ] **Step 1: Uruchom `robot_controller` na robocie**

Uruchom główną aplikację robota (tak jak normalnie), upewnij się że działa i przyjmuje komendy silnika przez WebSocket.

- [ ] **Step 2: Sprawdź że plik stanu kół się aktualizuje**

Run: `watch -n 0.2 cat /tmp/wheel_state.json`

Poruszaj robotem (np. przez istniejący interfejs sterowania) i sprawdź, że `t_mono` i `channels` w pliku zmieniają się na żywo.

- [ ] **Step 3: Obudź lidar i uruchom SLAM z odometrią**

Run: `cd ~/unilidar_sdk/unitree_lidar_sdk/bin && (echo "start"; sleep 20; echo "quitkeep") | ./lidar_l1_tester /dev/ttyUSB0`

Run: `cd ~/gremlin/robot_ws && ~/lidar_venv/bin/python lidar_slam.py --port /dev/ttyUSB0 --seconds 30 --odom-state-file /tmp/wheel_state.json --wheel-calibration wheel_calibration.json --map-out map_with_odom.csv --traj-out traj_with_odom.csv`

- [ ] **Step 4: Przejedź robotem po znanej, prostej trasie**

Podczas działania SLAM-u (30s), przejedź robotem do przodu po zmierzonej wcześniej, prostej trasie (np. 2 metry po podłodze z taśmą mierniczą).

- [ ] **Step 5: Porównaj estymowaną trajektorię z rzeczywistą**

Otwórz `traj_with_odom.csv` i sprawdź ostatnią pozycję `(x, y, z)`. Zmierzona długość przejazdu powinna być zbliżona do `sqrt(x^2 + y^2)` z ostatniego wiersza (w rozsądnej tolerancji — bez enkoderów i bez loop closure nie oczekujemy dokładności co do centymetra, ale rząd wielkości i kierunek powinny się zgadzać).

Sprawdź w logu stderr liczbę `odrzuconych ramek` — jeśli jest bardzo wysoka (>50%), guardy (`min-fitness`/divergencja) są prawdopodobnie zbyt restrykcyjne albo kalibracja `max_wheel_speed_rad_s` jest znacząco błędna, i wymaga to dalszej iteracji poza zakresem tego planu.

- [ ] **Step 6: Zapisz wynik walidacji**

Niezależnie od wyniku, zanotuj w commit message (Step 7) zmierzoną odległość, estymowaną odległość, i liczbę odrzuconych ramek — to dane wejściowe do ewentualnej kolejnej iteracji (np. decyzji o EKF, patrz spec).

- [ ] **Step 7: Commit**

```bash
cd ~/gremlin
git add robot_ws/map_with_odom.csv robot_ws/traj_with_odom.csv
git commit -m "test: end-to-end validation run of odometry-guided lidar SLAM"
```
