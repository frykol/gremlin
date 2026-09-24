# Wsparcie dla kontrolera USB (gamepad) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatyczne wykrywanie USB gamepada, zmapowanie jego przycisków/osi na nazwane kontrolki wg config.json, i broadcastowanie jego stanu na żywo (event-driven, tylko przy zmianie) do trzeciej aplikacji podłączonej po WiFi przez nowy, dedykowany WebSocket.

**Architecture:** Nowy moduł `src/hardware/gamepad/` (interface + real evdev-backed impl + dummy + factory) zbudowany 1:1 wg istniejącego wzorca hot-plug (`DeviceSlot` + `DeviceMonitor`, patrz `src/hardware/respeaker/`). Nowy `GamepadWorker` (analogiczny do `MicWorker`) w pętli czyta stan ze slota, zapisuje go do `RobotState`, i wysyła go — tylko gdy się zmienił — przez drugą, niezależną instancję istniejącej klasy `WsServer`, uruchomioną obok reszty workerów w `RobotController` (proces `program_manager`, wzorzec z `default.py`/`robot_controller.py`), a **nie** w `main.py` (`main.py` hostuje wyłącznie WsServer dla `site`/frontendu i nie ma dostępu do device slotów — te żyją w procesie potomnym `program_manager`).

**Tech Stack:** Python, `asyncio`, `evdev` (nowa zależność, odczyt `/dev/input/eventX`), `websockets` (już używane przez istniejący `WsServer`).

**Spec:** `docs/superpowers/specs/2026-09-10-gamepad-support-design.md`

## Global Constraints

- Testy uruchamiane przez `.venv/bin/python -m pytest <ścieżka> -q` z katalogu repo (samo `pytest` nie widzi pakietu `src`).
- Nowy kod musi zachować dokładnie wzorzec hot-plug z `src/hardware/respeaker/` (interface ABC + real + dummy z `IS_DUMMY = True` + `factory.py` z `_build_dummy`/`_build_real`/`create_*`) — patrz `src/hardware/respeaker/factory.py:1-73` jako referencyjny przykład.
- `_build_real`/`_build_dummy` MUSZĄ same wołać `.start()` na zwracanej instancji (komentarz w `respeaker/factory.py:19-23` tłumaczy dlaczego: `DeviceMonitor` podmienia instancję w trakcie działania, żaden worker nie wywoła `.start()` po raz drugi).
- Import `evdev` musi być leniwy (wewnątrz `_build_real`, nie na górze `factory.py`), żeby moduł dało się zaimportować i przetestować bez zainstalowanego `evdev`/prawdziwego sprzętu — patrz `respeaker/factory.py:28` (`from .respeaker import ReSpeakerMicArray` wewnątrz funkcji).
- Import samego `gamepad.py` (plik z prawdziwą implementacją na `evdev`) może zakładać, że `evdev` jest zainstalowane — nie jest importowany przez żaden test w tym planie.
- Nowy websocket dla trzeciej aplikacji: jeden klient, bez autoryzacji (jak dzisiejszy `WsServer`) — nie dodawać auth/multi-client.
- Poza zakresem: tłumaczenie stanu gamepada na komendy sterowania robotem.

---

## Task 1: Czysta logika mapowania evdev → nazwane kontrolki

**Files:**
- Create: `src/hardware/gamepad/__init__.py` (pusty)
- Create: `src/hardware/gamepad/interface.py`
- Create: `src/hardware/gamepad/mapping.py`
- Test: `tests/test_gamepad_mapping.py`

**Interfaces:**
- Produces: `GamepadState` (dataclass: `buttons: dict[str, bool]`, `axes: dict[str, float]`, oba domyślnie puste dict-y), `GamepadInterface` (ABC: `start()`, `stop()`, `get_state() -> GamepadState`, `is_healthy() -> bool`), `is_button_code(code_name: str) -> bool`, `is_axis_code(code_name: str) -> bool`, `neutral_state(mapping: dict[str, str]) -> GamepadState`, `normalize_axis_value(raw_value: int, abs_min: int, abs_max: int) -> float`. Wszystkie te nazwy są używane dosłownie w Task 2-5.

- [ ] **Step 1: Napisz `src/hardware/gamepad/__init__.py` (pusty plik)**

```python
```

- [ ] **Step 2: Napisz `src/hardware/gamepad/interface.py`**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class GamepadState:
    buttons: dict[str, bool] = field(default_factory=dict)
    axes: dict[str, float] = field(default_factory=dict)


class GamepadInterface(ABC):
    @abstractmethod
    def start(self) -> None:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass

    @abstractmethod
    def get_state(self) -> GamepadState:
        pass

    @abstractmethod
    def is_healthy(self) -> bool:
        pass
```

- [ ] **Step 3: Napisz failing test dla mapowania (`tests/test_gamepad_mapping.py`)**

```python
import pytest

from src.hardware.gamepad.mapping import (
    is_button_code,
    is_axis_code,
    neutral_state,
    normalize_axis_value,
)


def test_is_button_code_matches_btn_prefix():
    assert is_button_code("BTN_SOUTH") is True
    assert is_button_code("ABS_X") is False


def test_is_axis_code_matches_abs_prefix():
    assert is_axis_code("ABS_X") is True
    assert is_axis_code("BTN_SOUTH") is False


def test_neutral_state_splits_buttons_and_axes_by_prefix():
    mapping = {"BTN_SOUTH": "a", "ABS_X": "left_stick_x", "BTN_EAST": "b"}

    state = neutral_state(mapping)

    assert state.buttons == {"a": False, "b": False}
    assert state.axes == {"left_stick_x": 0.0}


def test_normalize_axis_value_maps_range_to_minus_one_one():
    assert normalize_axis_value(0, 0, 255) == -1.0
    assert normalize_axis_value(255, 0, 255) == 1.0
    assert normalize_axis_value(127, 0, 255) == pytest.approx(-0.00392, abs=1e-4)


def test_normalize_axis_value_clamps_out_of_range_input():
    assert normalize_axis_value(-10, 0, 255) == -1.0
    assert normalize_axis_value(300, 0, 255) == 1.0


def test_normalize_axis_value_handles_degenerate_range():
    assert normalize_axis_value(5, 5, 5) == 0.0
```

- [ ] **Step 4: Uruchom test i sprawdź, że pada**

Run: `.venv/bin/python -m pytest tests/test_gamepad_mapping.py -q`
Expected: FAIL z `ModuleNotFoundError: No module named 'src.hardware.gamepad.mapping'`

- [ ] **Step 5: Napisz `src/hardware/gamepad/mapping.py`**

```python
from .interface import GamepadState

BUTTON_PREFIX = "BTN_"
AXIS_PREFIX = "ABS_"


def is_button_code(code_name: str) -> bool:
    return code_name.startswith(BUTTON_PREFIX)


def is_axis_code(code_name: str) -> bool:
    return code_name.startswith(AXIS_PREFIX)


def neutral_state(mapping: dict[str, str]) -> GamepadState:
    buttons = {name: False for code, name in mapping.items() if is_button_code(code)}
    axes = {name: 0.0 for code, name in mapping.items() if is_axis_code(code)}
    return GamepadState(buttons=buttons, axes=axes)


def normalize_axis_value(raw_value: int, abs_min: int, abs_max: int) -> float:
    """Mapuje surowa wartosc evdev z zakresu [abs_min, abs_max] na [-1.0, 1.0],
    przycinajac wartosci wykraczajace poza zakres raportowany przez urzadzenie."""
    if abs_max == abs_min:
        return 0.0

    span = abs_max - abs_min
    normalized = (2 * (raw_value - abs_min) / span) - 1.0
    return max(-1.0, min(1.0, normalized))
```

- [ ] **Step 6: Uruchom test i sprawdź, że przechodzi**

Run: `.venv/bin/python -m pytest tests/test_gamepad_mapping.py -q`
Expected: PASS (6 testów)

- [ ] **Step 7: Commit**

```bash
git add src/hardware/gamepad/__init__.py src/hardware/gamepad/interface.py src/hardware/gamepad/mapping.py tests/test_gamepad_mapping.py
git commit -m "feat(gamepad): add GamepadInterface/GamepadState and evdev mapping helpers"
```

---

## Task 2: Dummy gamepad

**Files:**
- Create: `src/hardware/gamepad/dummy_gamepad.py`
- Test: `tests/test_gamepad_factory.py` (tylko test dummy w tym tasku — real+factory w Task 4)

**Interfaces:**
- Consumes: `GamepadInterface`, `GamepadState`, `neutral_state` z Task 1.
- Produces: `FakeGamepad(GamepadInterface)` z `IS_DUMMY = True`, konstruktor `FakeGamepad(mapping: dict[str, str] | None = None)`, atrybut `running: bool`. Task 3 (factory) importuje `FakeGamepad` z tego pliku.

- [ ] **Step 1: Napisz failing test**

```python
from src.hardware.gamepad.dummy_gamepad import FakeGamepad


def test_dummy_gamepad_starts_and_returns_neutral_state_from_mapping():
    mapping = {"BTN_SOUTH": "a", "ABS_X": "left_stick_x"}
    gamepad = FakeGamepad(mapping=mapping)

    gamepad.start()

    assert gamepad.running is True
    state = gamepad.get_state()
    assert state.buttons == {"a": False}
    assert state.axes == {"left_stick_x": 0.0}
    assert gamepad.is_healthy() is True

    gamepad.stop()
    assert gamepad.running is False
```

- [ ] **Step 2: Uruchom test i sprawdź, że pada**

Run: `.venv/bin/python -m pytest tests/test_gamepad_factory.py -q`
Expected: FAIL z `ModuleNotFoundError: No module named 'src.hardware.gamepad.dummy_gamepad'`

- [ ] **Step 3: Napisz `src/hardware/gamepad/dummy_gamepad.py`**

```python
from .interface import GamepadInterface, GamepadState
from .mapping import neutral_state


class FakeGamepad(GamepadInterface):
    IS_DUMMY = True

    def __init__(self, mapping: dict[str, str] | None = None):
        self.mapping = mapping or {}
        self.running: bool = False

    def start(self) -> None:
        self.running = True
        print("Gamepad (dummy) działa")

    def stop(self) -> None:
        self.running = False
        print("Gamepad (dummy) zatrzymany")

    def get_state(self) -> GamepadState:
        return neutral_state(self.mapping)

    def is_healthy(self) -> bool:
        return True
```

- [ ] **Step 4: Uruchom test i sprawdź, że przechodzi**

Run: `.venv/bin/python -m pytest tests/test_gamepad_factory.py -q`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add src/hardware/gamepad/dummy_gamepad.py tests/test_gamepad_factory.py
git commit -m "feat(gamepad): add dummy gamepad implementation"
```

---

## Task 3: Real gamepad (evdev)

**Files:**
- Create: `src/hardware/gamepad/gamepad.py`
- Modify: `requirements.txt` (dodaj `evdev`)

**Interfaces:**
- Consumes: `GamepadInterface`, `GamepadState`, `is_button_code`, `is_axis_code`, `neutral_state`, `normalize_axis_value` z Task 1.
- Produces: `find_gamepad_device() -> evdev.InputDevice` (rzuca `RuntimeError` gdy brak urządzenia), `Gamepad(GamepadInterface)` z konstruktorem `Gamepad(mapping: dict[str, str])`. Task 4 (factory) importuje `Gamepad` z tego pliku wewnątrz `_build_real` (leniwy import — patrz Global Constraints).

Ten task nie ma testów jednostkowych — wymaga fizycznego evdev/gamepada, tak samo jak `src/hardware/respeaker/respeaker.py` czy `src/hardware/lidar/unitree_l1.py` nie mają testów jednostkowych w tym repo (weryfikacja na realnym sprzęcie, poza automatycznym test suite). Poprawność jest pokryta pośrednio przez testy `mapping.py` (Task 1) i testy factory/workera z mockami (Task 4-5).

- [ ] **Step 1: Dodaj zależność do `requirements.txt`**

Dopisz `evdev` na końcu pliku `requirements.txt` (po `vosk`).

- [ ] **Step 2: Zainstaluj zależność w wirtualnym środowisku**

Run: `.venv/bin/pip install evdev`
Expected: instalacja się powiedzie (na Raspberry Pi/Linuksie; pakiet ma natywne rozszerzenie, wymaga nagłówków Linux — jeśli instalacja padnie na tej maszynie deweloperskiej z powodu braku `/usr/include/linux/input.h`, zainstaluj `python3-dev`/`libevdev-dev` albo pomiń ten krok lokalnie i zweryfikuj dopiero na docelowym RPi, gdzie te nagłówki są standardowo obecne).

- [ ] **Step 3: Napisz `src/hardware/gamepad/gamepad.py`**

```python
import asyncio
from typing import Optional

import evdev
from evdev import ecodes

from .interface import GamepadInterface, GamepadState
from .mapping import is_button_code, is_axis_code, neutral_state, normalize_axis_value


def _resolve_code_name(table: dict, code: int) -> Optional[str]:
    name = table.get(code)
    if isinstance(name, list):
        return name[0] if name else None
    return name


def find_gamepad_device() -> "evdev.InputDevice":
    for path in evdev.list_devices():
        device = evdev.InputDevice(path)
        caps = device.capabilities()
        if ecodes.EV_KEY in caps and ecodes.EV_ABS in caps:
            return device
        device.close()

    raise RuntimeError("Nie znaleziono podlaczonego gamepada (brak urzadzenia EV_KEY+EV_ABS w /dev/input)")


class Gamepad(GamepadInterface):
    def __init__(self, mapping: dict[str, str]):
        self.mapping = mapping
        self.device: Optional["evdev.InputDevice"] = None
        self._state: GamepadState = neutral_state(mapping)
        self._abs_ranges: dict[str, tuple[int, int]] = {}
        self._read_task: Optional[asyncio.Task] = None
        self._healthy: bool = False

    def start(self) -> None:
        self.device = find_gamepad_device()
        self._healthy = True

        for code, absinfo in self.device.capabilities().get(ecodes.EV_ABS, []):
            code_name = _resolve_code_name(ecodes.bytype[ecodes.EV_ABS], code)
            if code_name is not None:
                self._abs_ranges[code_name] = (absinfo.min, absinfo.max)

        self._read_task = asyncio.get_event_loop().create_task(self._read_loop())
        print(f"Gamepad wykryty: {self.device.name} ({self.device.path})")

    def stop(self) -> None:
        if self._read_task is not None:
            self._read_task.cancel()
            self._read_task = None

        if self.device is not None:
            try:
                self.device.close()
            except Exception:
                pass
            self.device = None

        self._healthy = False
        print("Gamepad zatrzymany")

    def get_state(self) -> GamepadState:
        return GamepadState(buttons=dict(self._state.buttons), axes=dict(self._state.axes))

    def is_healthy(self) -> bool:
        return self._healthy

    async def _read_loop(self) -> None:
        assert self.device is not None
        try:
            async for event in self.device.async_read_loop():
                self._handle_event(event)
        except OSError as e:
            # Pad odlaczony w trakcie dzialania (np. wyjety kabel USB) -
            # bez tego except petla po prostu by sie ubila, is_healthy()
            # nigdy by nie zwrocilo False, i DeviceMonitor nigdy by nie
            # przelaczyl slota na dummy.
            print(f"Gamepad read error (device disconnected?): {e}")
            self._healthy = False

    def _handle_event(self, event) -> None:
        if event.type == ecodes.EV_KEY:
            code_name = _resolve_code_name(ecodes.bytype[ecodes.EV_KEY], event.code)
            if code_name is None or not is_button_code(code_name):
                return
            name = self.mapping.get(code_name)
            if name is not None:
                self._state.buttons[name] = bool(event.value)

        elif event.type == ecodes.EV_ABS:
            code_name = _resolve_code_name(ecodes.bytype[ecodes.EV_ABS], event.code)
            if code_name is None or not is_axis_code(code_name):
                return
            name = self.mapping.get(code_name)
            if name is None:
                return
            abs_min, abs_max = self._abs_ranges.get(code_name, (-1, 1))
            self._state.axes[name] = normalize_axis_value(event.value, abs_min, abs_max)
```

- [ ] **Step 4: Sprawdź, że moduł się importuje bez błędów składniowych**

Run: `.venv/bin/python -c "import ast; ast.parse(open('src/hardware/gamepad/gamepad.py').read())"`
Expected: brak błędu (bez wypisania niczego = sukces)

(Pełny `import src.hardware.gamepad.gamepad` wymaga zainstalowanego `evdev` z Kroku 2 — jeśli krok 2 został pominięty na tej maszynie, ogranicz się do sprawdzenia składni; pełna weryfikacja importu i działania nastąpi na docelowym RPi.)

- [ ] **Step 5: Commit**

```bash
git add requirements.txt src/hardware/gamepad/gamepad.py
git commit -m "feat(gamepad): add real evdev-backed gamepad implementation"
```

---

## Task 4: Factory z hot-plug (DeviceSlot + DeviceMonitor)

**Files:**
- Create: `src/hardware/gamepad/factory.py`
- Modify: `tests/test_gamepad_factory.py` (dopisz testy factory obok testu dummy z Task 2)
- Modify: `tests/test_dummy_hot_swap_started.py` (dopisz test analogiczny do pozostałych urządzeń)

**Interfaces:**
- Consumes: `GamepadInterface` (Task 1), `FakeGamepad` (Task 2), `log_device_status` (`src/hardware/status_log.py`), `DeviceSlot` (`src/hardware/device_slot.py`), `DeviceMonitor`/`start_device_monitor` (`src/hardware/device_monitor.py`).
- Produces: `_build_dummy(config: dict) -> GamepadInterface`, `_build_real(config: dict) -> GamepadInterface`, `create_gamepad(config: dict) -> DeviceSlot`. Task 5 (worker) i Task 6 (wiring) importują `create_gamepad` z `src.hardware.gamepad.factory`.

- [ ] **Step 1: Napisz failing testy factory (dopisz do `tests/test_gamepad_factory.py`)**

```python
from src.hardware.gamepad.factory import _build_dummy, create_gamepad
from src.hardware.device_slot import DeviceSlot


def test_build_dummy_gamepad_is_already_started():
    gamepad = _build_dummy({"gamepad": {"mapping": {"BTN_SOUTH": "a"}}})

    assert gamepad.running is True
    assert gamepad.get_state().buttons == {"a": False}


def test_create_gamepad_with_is_dummy_flag_returns_dummy_slot_without_monitor():
    slot = create_gamepad({"gamepad": {"is_dummy": True, "mapping": {}}})

    assert isinstance(slot, DeviceSlot)
    assert slot.get().IS_DUMMY is True
    assert slot.monitor_task is None


def test_create_gamepad_falls_back_to_dummy_when_no_real_device_available():
    # Brak sekcji "gamepad"/is_dummy=False -> probuje _build_real, ktora na
    # maszynie bez podlaczonego evdev-gamepada rzuci (RuntimeError z braku
    # urzadzenia albo ImportError jesli evdev nie jest zainstalowane) -
    # create_gamepad musi to zlapac i wystawic dzialajacego dummy zamiast
    # crashowac caly proces.
    slot = create_gamepad({"gamepad": {"is_dummy": False, "mapping": {}}})

    assert isinstance(slot, DeviceSlot)
    assert slot.get().IS_DUMMY is True
```

- [ ] **Step 2: Uruchom testy i sprawdź, że padają**

Run: `.venv/bin/python -m pytest tests/test_gamepad_factory.py -q`
Expected: FAIL z `ModuleNotFoundError: No module named 'src.hardware.gamepad.factory'`

- [ ] **Step 3: Napisz `src/hardware/gamepad/factory.py`**

```python
from .interface import GamepadInterface
from .dummy_gamepad import FakeGamepad
from ..status_log import log_device_status
from ..device_slot import DeviceSlot
from ..device_monitor import DeviceMonitor, start_device_monitor

DEVICE_NAME = "GAMEPAD"


def _build_dummy(config: dict) -> GamepadInterface:
    gamepad_config = config.get("gamepad", {})
    gamepad = FakeGamepad(mapping=gamepad_config.get("mapping", {}))
    # DeviceMonitor podmienia instancje w slocie w trakcie dzialania robota -
    # zaden worker nie wywola juz .start() na tej nowej instancji, wiec
    # musimy ja wystartowac tutaj (patrz respeaker/factory.py po ten sam
    # wzorzec i uzasadnienie).
    gamepad.start()
    return gamepad


def _build_real(config: dict) -> GamepadInterface:
    from .gamepad import Gamepad

    gamepad_config = config.get("gamepad", {})
    gamepad = Gamepad(mapping=gamepad_config.get("mapping", {}))
    gamepad.start()
    return gamepad


def create_gamepad(config: dict) -> DeviceSlot:
    gamepad_config = config.get("gamepad", {})
    is_dummy = gamepad_config.get("is_dummy", False)
    poll_interval = config.get("device_health_check_interval", 5.0)

    if is_dummy:
        log_device_status(DEVICE_NAME, "SUCCESS - DUMMY")
        return DeviceSlot(_build_dummy(config))

    try:
        instance: GamepadInterface = _build_real(config)
        log_device_status(DEVICE_NAME, "SUCCESS")
    except Exception as e:
        log_device_status(DEVICE_NAME, "ERROR")
        print(f"Failed to initialize {DEVICE_NAME}: {e}")
        log_device_status(DEVICE_NAME, "ERROR - FALLBACK TO DUMMY")
        instance = _build_dummy(config)

    slot = DeviceSlot(instance)

    monitor = DeviceMonitor(
        name=DEVICE_NAME,
        slot=slot,
        build_real=lambda: _build_real(config),
        build_dummy=lambda: _build_dummy(config),
        poll_interval=poll_interval,
    )
    slot.monitor_task = start_device_monitor(monitor)

    return slot
```

- [ ] **Step 4: Uruchom testy i sprawdź, że przechodzą**

Run: `.venv/bin/python -m pytest tests/test_gamepad_factory.py -q`
Expected: PASS (4 testy łącznie z Task 2)

- [ ] **Step 5: Dopisz test hot-swap do `tests/test_dummy_hot_swap_started.py`**

Dodaj import na górze pliku (obok istniejących):
```python
from src.hardware.gamepad.factory import _build_dummy as build_dummy_gamepad
```

Dodaj funkcję testową na końcu pliku:
```python
def test_build_dummy_gamepad_is_already_started():
    gamepad = build_dummy_gamepad({"gamepad": {"mapping": {"BTN_SOUTH": "a"}}})
    assert gamepad.running is True
    assert gamepad.get_state().buttons == {"a": False}
```

- [ ] **Step 6: Uruchom cały plik i sprawdź, że przechodzi**

Run: `.venv/bin/python -m pytest tests/test_dummy_hot_swap_started.py -q`
Expected: PASS (6 testów)

- [ ] **Step 7: Commit**

```bash
git add src/hardware/gamepad/factory.py tests/test_gamepad_factory.py tests/test_dummy_hot_swap_started.py
git commit -m "feat(gamepad): add factory with DeviceSlot/DeviceMonitor hot-plug wiring"
```

---

## Task 5: GamepadWorker (poll + diff + push do nowego WsServer)

**Files:**
- Create: `src/workers/gamepad_worker.py`
- Modify: `src/robot_state.py` (dodaj pole `gamepad_state`)
- Test: `tests/test_gamepad_worker.py`

**Interfaces:**
- Consumes: `resolve` (`src/hardware/device_slot.py`), `GamepadState`/`GamepadInterface` (Task 1), `RobotState` (`src/robot_state.py`), `WsServer` (`src/dev_connection/ws_server.py`, tylko jako type hint — testy wstrzykują dowolny obiekt z metodą `async send(str)`).
- Produces: `GamepadWorker(gamepad, state: RobotState, gamepad_ws, poll_interval: float = 0.005)` z metodami `start()` (sync) i `async stop()`, atrybutami `running: bool`, `task: asyncio.Task | None`. Task 6 (wiring) tworzy instancję tej klasy w `RobotController`.

- [ ] **Step 1: Dodaj pole do `RobotState`**

W `src/robot_state.py` dodaj import na górze pliku:
```python
from .hardware.gamepad.interface import GamepadState
```

I dodaj pole w dataclass `RobotState` (obok pozostałych `*_state`):
```python
    gamepad_state: GamepadState | None = None
```

- [ ] **Step 2: Napisz failing testy workera**

```python
"""GamepadWorker musi (a) przezyc pojedynczy blad odczytu z gamepada -
patrz ten sam problem naprawiony w CameraWorker/LidarWorker/MicWorker
(tests/test_worker_read_error_resilience.py) - i (b) wysylac stan do
gamepad_ws TYLKO gdy sie faktycznie zmienil, zeby nie zasypywac trzeciej
aplikacji identycznymi wiadomosciami przy kazdej iteracji petli."""

import asyncio
import json

from src.hardware.gamepad.interface import GamepadState
from src.robot_state import RobotState
from src.workers.gamepad_worker import GamepadWorker


class FlakyGamepad:
    def __init__(self):
        self.calls = 0

    def start(self):
        pass

    def stop(self):
        pass

    def get_state(self):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("evdev device disappeared")
        return GamepadState(buttons={"a": True}, axes={})


class ScriptedGamepad:
    def __init__(self, states):
        self.states = states
        self.calls = 0

    def start(self):
        pass

    def stop(self):
        pass

    def get_state(self):
        index = min(self.calls, len(self.states) - 1)
        self.calls += 1
        return self.states[index]


class RecordingWs:
    def __init__(self):
        self.sent = []

    async def send(self, message):
        self.sent.append(message)


async def _run_worker_briefly(worker, duration=0.05):
    worker.start()
    await asyncio.sleep(duration)
    worker.running = False
    if worker.task is not None:
        await worker.task


def test_gamepad_worker_survives_read_error_and_keeps_polling():
    async def scenario():
        gamepad = FlakyGamepad()
        state = RobotState()
        worker = GamepadWorker(gamepad=gamepad, state=state, gamepad_ws=RecordingWs(), poll_interval=0.001)

        await _run_worker_briefly(worker)

        assert gamepad.calls > 1
        assert state.gamepad_state is not None
        assert state.gamepad_state.buttons == {"a": True}

    asyncio.run(scenario())


def test_gamepad_worker_sends_only_on_state_change():
    async def scenario():
        states = [
            GamepadState(buttons={"a": False}, axes={}),
            GamepadState(buttons={"a": False}, axes={}),
            GamepadState(buttons={"a": False}, axes={}),
            GamepadState(buttons={"a": True}, axes={}),
            GamepadState(buttons={"a": True}, axes={}),
        ]
        gamepad = ScriptedGamepad(states)
        ws = RecordingWs()
        state = RobotState()
        worker = GamepadWorker(gamepad=gamepad, state=state, gamepad_ws=ws, poll_interval=0.001)

        await _run_worker_briefly(worker, duration=0.08)

        assert gamepad.calls > len(states)
        assert len(ws.sent) == 2

        first = json.loads(ws.sent[0])
        second = json.loads(ws.sent[1])
        assert first["type"] == "gamepad_state"
        assert first["buttons"] == {"a": False}
        assert second["buttons"] == {"a": True}

    asyncio.run(scenario())
```

- [ ] **Step 3: Uruchom testy i sprawdź, że padają**

Run: `.venv/bin/python -m pytest tests/test_gamepad_worker.py -q`
Expected: FAIL z `ModuleNotFoundError: No module named 'src.workers.gamepad_worker'`

- [ ] **Step 4: Napisz `src/workers/gamepad_worker.py`**

```python
import asyncio
import json

from src.hardware.device_slot import resolve
from src.hardware.gamepad.interface import GamepadState
from src.robot_state import RobotState


class GamepadWorker:
    def __init__(self, gamepad, state: RobotState, gamepad_ws, poll_interval: float = 0.005):
        self.gamepad = gamepad
        self.state: RobotState = state
        self.gamepad_ws = gamepad_ws
        self.poll_interval: float = poll_interval

        self.running: bool = False
        self.task: asyncio.Task | None = None
        self._last_sent: GamepadState | None = None

    async def run(self):
        while self.running:
            try:
                current = resolve(self.gamepad).get_state()
            except Exception as exc:
                # Bez tego try/except wyjatek z realnego sprzetu (np. evdev
                # device disappearing on USB unplug) ubijalby cala petle na
                # stale - patrz ten sam problem naprawiony w
                # CameraWorker/LidarWorker/MicWorker.
                print(f"Gamepad read error: {exc}")
                current = None

            if current is not None:
                self.state.gamepad_state = current

                if current != self._last_sent:
                    self._last_sent = GamepadState(buttons=dict(current.buttons), axes=dict(current.axes))
                    try:
                        await self.gamepad_ws.send(json.dumps({
                            "type": "gamepad_state",
                            "buttons": current.buttons,
                            "axes": current.axes,
                        }))
                    except Exception as exc:
                        print(f"Failed to send gamepad state: {exc}")

            await asyncio.sleep(self.poll_interval)

    def start(self):
        if self.running:
            return

        resolve(self.gamepad).start()

        self.running = True
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        self.running = False

        if self.task is not None:
            await self.task

        resolve(self.gamepad).stop()
```

- [ ] **Step 5: Uruchom testy i sprawdź, że przechodzą**

Run: `.venv/bin/python -m pytest tests/test_gamepad_worker.py -q`
Expected: PASS (2 testy)

- [ ] **Step 6: Uruchom pełny istniejący test suite dla robot_state, żeby upewnić się, że nowe pole niczego nie zepsuło**

Run: `.venv/bin/python -m pytest tests/ -k "robot_state or gamepad" -q`
Expected: PASS, brak błędów importu

- [ ] **Step 7: Commit**

```bash
git add src/robot_state.py src/workers/gamepad_worker.py tests/test_gamepad_worker.py
git commit -m "feat(gamepad): add GamepadWorker with diff-based push to gamepad_ws"
```

---

## Task 6: Wpięcie do RobotController/default.py + config.json (drugi WsServer)

**Files:**
- Modify: `config.json`
- Modify: `src/robot_controller.py`
- Modify: `src/default.py`

**Interfaces:**
- Consumes: `create_gamepad` (Task 4), `GamepadWorker` (Task 5), `WsServer` (`src/dev_connection/ws_server.py`, już istnieje, sygnatura `WsServer(host, port, instruction_tab)` z metodami `async connect()`, `async send(message)`, `async close()`).
- Nie produkuje nowych publicznych interfejsów dla innych tasków — to ostatni task tego planu.

- [ ] **Step 1: Dodaj sekcje `gamepad` i `gamepad_ws_server` do `config.json`**

Dodaj sekcję `"gamepad"` zaraz po sekcji `"respeaker"` (przed `"speaker"`):
```json
  "gamepad": {
    "is_dummy": true,
    "mapping": {
      "BTN_SOUTH": "a",
      "BTN_EAST": "b",
      "BTN_WEST": "x",
      "BTN_NORTH": "y",
      "BTN_TL": "bumper_l",
      "BTN_TR": "bumper_r",
      "BTN_START": "start",
      "BTN_SELECT": "back",
      "ABS_X": "left_stick_x",
      "ABS_Y": "left_stick_y",
      "ABS_RX": "right_stick_x",
      "ABS_RY": "right_stick_y",
      "ABS_Z": "trigger_l",
      "ABS_RZ": "trigger_r"
    }
  },
```

Dodaj sekcję `"gamepad_ws_server"` zaraz po istniejącej sekcji `"ws_server"`:
```json
  "gamepad_ws_server": {
    "host": "0.0.0.0",
    "port": 8768
  },
```

`is_dummy: true` jako bezpieczny domyślny (tak samo jak dziś `respeaker.is_dummy: true`) — zmienić na `false` dopiero po sprawdzeniu na docelowym sprzęcie z podłączonym padem.

- [ ] **Step 2: Sprawdź, że `config.json` nadal jest poprawnym JSON-em**

Run: `.venv/bin/python -c "import json; json.load(open('config.json'))"`
Expected: brak błędu

- [ ] **Step 3: Wpięcie w `src/robot_controller.py`**

Zmodyfikuj importy na górze pliku (dodaj obok pozostałych `from .workers...`):
```python
from .workers.gamepad_worker import GamepadWorker
from .dev_connection.ws_server import WsServer
```

Zmodyfikuj sygnaturę `__init__` (dodaj parametr `gamepad: DeviceSlot` na końcu listy parametrów, przed `ws`):
```python
    def __init__(self, config: dict, command_queue: asyncio.Queue, gpio: GPIOController, encoder: EncoderController, i2c_pwm: DeviceSlot, camera: DeviceSlot, mic_array: DeviceSlot, sd_card: DeviceSlot, ads1115: DeviceSlot, lidar: DeviceSlot, speaker: DeviceSlot, gamepad: DeviceSlot, ws: WSClientInterface):
```

W ciele `__init__`, zaraz po bloku `self.mic_worker = MicWorker(...)`, dodaj:
```python
        gamepad_ws_config = config.get("gamepad_ws_server", {})

        self.gamepad_ws = WsServer(
            host=gamepad_ws_config.get("host", "0.0.0.0"),
            port=gamepad_ws_config.get("port", 8768),
            instruction_tab=asyncio.Queue(),
        )

        self.gamepad_worker = GamepadWorker(
            state=self.state,
            gamepad=gamepad,
            gamepad_ws=self.gamepad_ws,
        )
```

W metodzie `run()`, w liście `tasks = [...]`, dodaj wpis:
```python
            asyncio.create_task(self.gamepad_ws.connect()),
```

Tuż przed `tasks = [` (obok `self.color_detection_worker.start()`), dodaj:
```python
        self.gamepad_worker.start()
```

W bloku `finally:`, obok `await self.color_detection_worker.stop()`, dodaj:
```python
            await self.gamepad_worker.stop()
            await self.gamepad_ws.close()
```

- [ ] **Step 4: Wpięcie w `src/default.py`**

Dodaj import na górze pliku:
```python
from .hardware.gamepad.factory import create_gamepad
```

W `init()`, obok `speaker_slot = create_speaker(config)`, dodaj:
```python
    gamepad_slot = create_gamepad(config)
```

W wywołaniu `RobotController(...)`, dodaj argument `gamepad=gamepad_slot` (przed `ws=ws`):
```python
    _robot = RobotController(
        config=config,
        command_queue=r_tab,
        gpio=gpio_c,
        encoder=encoder_c,
        i2c_pwm=i2c_pwm_slot,
        camera=camera_slot,
        mic_array=mic_array_slot,
        sd_card=sd_card_slot,
        ads1115=ads1115_slot,
        lidar=lidar_slot,
        speaker=speaker_slot,
        gamepad=gamepad_slot,
        ws=ws
    )
```

- [ ] **Step 5: Sprawdź składnię obu zmienionych plików**

Run: `.venv/bin/python -c "import ast; ast.parse(open('src/robot_controller.py').read()); ast.parse(open('src/default.py').read())"`
Expected: brak błędu

- [ ] **Step 6: Uruchom cały istniejący test suite, żeby upewnić się że nic nie zostało zepsute**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS na wszystkich testach (łącznie z nowymi z Task 1-5); brak błędów collection w `test_camera_factory.py`, `test_dummy_hot_swap_started.py`, `test_worker_read_error_resilience.py` i innych plikach dotykających `RobotController`/`default.py` pośrednio przez importy.

- [ ] **Step 7: Commit**

```bash
git add config.json src/robot_controller.py src/default.py
git commit -m "feat(gamepad): wire GamepadWorker and dedicated WsServer into RobotController"
```

---

## Ręczna weryfikacja na docelowym sprzęcie (poza automatycznym test suite)

Po wdrożeniu na Raspberry Pi z podłączonym gamepadem USB:

1. Ustaw `"gamepad": {"is_dummy": false, ...}` w `config.json`.
2. Uruchom `python3 -m src.program_manager` (albo cały `gremlin.service`) i sprawdź w logu (`current_simulation_status.log`) linię `GAMEPAD SUCCESS`.
3. Z innej maszyny w tej samej sieci WiFi połącz się websocketem (np. `wscat -c ws://<ip-rpi>:8768`) i poruszając padem sprawdź, że przychodzą wiadomości `{"type": "gamepad_state", "buttons": {...}, "axes": {...}}` tylko przy zmianie stanu, a nie w sposób ciągły.
4. Odłącz pada w trakcie działania i sprawdź w logu przełączenie na `GAMEPAD ERROR - FALLBACK TO DUMMY` (po `device_health_check_interval` sekund).
