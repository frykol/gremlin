import asyncio
import concurrent.futures
from typing import Optional

import evdev
from evdev import ecodes

from .interface import GamepadInterface, GamepadState
from .mapping import neutral_state, normalize_axis_value


def _resolve_mapped_name(table: dict, code: int, mapping: dict[str, str]) -> Optional[str]:
    """Evdev raportuje ten sam kod fizycznego przycisku pod kilkoma aliasami
    naraz (np. kod 304 to jednoczesnie BTN_A, BTN_GAMEPAD i BTN_SOUTH) - ktora
    nazwa jest pierwsza na liscie zalezy od konkretnego pada. Sprawdzamy
    WSZYSTKIE aliasy przeciwko config.json, zamiast zawsze brac pierwszy -
    inaczej przycisk pod aliasem spoza pierwszej pozycji byłby cicho gubiony
    (np. SHANWAN Android Gamepad zglasza BTN_A/BTN_B jako pierwsze aliasy dla
    przyciskow A/B, wiec mapowanie oparte tylko na BTN_SOUTH/BTN_EAST nigdy by
    ich nie zlapalo)."""
    aliases = table.get(code)
    if aliases is None:
        return None
    if isinstance(aliases, str):
        aliases = (aliases,)

    for alias in aliases:
        if alias in mapping:
            return mapping[alias]

    return None


def find_gamepad_device() -> "evdev.InputDevice":
    for path in evdev.list_devices():
        try:
            device = evdev.InputDevice(path)
        except OSError:
            continue

        caps = device.capabilities()
        key_codes = caps.get(ecodes.EV_KEY, [])
        if ecodes.EV_ABS in caps and ecodes.BTN_GAMEPAD in key_codes:
            return device

        device.close()

    raise RuntimeError("Nie znaleziono podlaczonego gamepada (brak urzadzenia z EV_ABS i BTN_GAMEPAD w /dev/input)")


class Gamepad(GamepadInterface):
    def __init__(self, mapping: dict[str, str], loop: asyncio.AbstractEventLoop):
        self.mapping = mapping
        self.loop = loop
        self.device: Optional["evdev.InputDevice"] = None
        self._state: GamepadState = neutral_state(mapping)
        self._abs_ranges: dict[int, tuple[int, int]] = {}
        self._read_future: Optional[concurrent.futures.Future] = None
        self._healthy: bool = False

    def start(self) -> None:
        if self.device is not None:
            return

        self.device = find_gamepad_device()
        self._healthy = True

        for code, absinfo in self.device.capabilities().get(ecodes.EV_ABS, []):
            # Kluczujemy po surowym kodzie evdev (int), nie po nazwie - nazwa
            # zalezy od tego, ktory alias akurat zwroci _resolve_mapped_name,
            # a zakres musi byc jednoznaczny niezaleznie od tego wyboru.
            self._abs_ranges[code] = (absinfo.min, absinfo.max)

        # Gamepad.start() bywa wolane z watku executor-a (DeviceMonitor
        # buduje swiezy real driver przez run_in_executor, ktory nie ma
        # wlasnego running loopa) - run_coroutine_threadsafe, w
        # przeciwienstwie do loop.create_task, jest bezpieczne do wywolania
        # z dowolnego watku i planuje coroutine na docelowym loopie.
        self._read_future = asyncio.run_coroutine_threadsafe(self._read_loop(), self.loop)
        print(f"Gamepad wykryty: {self.device.name} ({self.device.path})")

    def stop(self) -> None:
        if self._read_future is not None:
            self._read_future.cancel()
            self._read_future = None

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
        except Exception as e:
            # Pad odlaczony w trakcie dzialania (np. wyjety kabel USB) albo
            # dowolny inny blad odczytu - bez tego except (i bez lapania
            # WSZYSTKICH wyjatkow, nie tylko OSError) petla po prostu by sie
            # ubila, is_healthy() nigdy by nie zwrocilo False, i
            # DeviceMonitor nigdy by nie przelaczyl slota na dummy - pad
            # wygladalby na podlaczony, ale zamrozony na ostatnim stanie.
            print(f"Gamepad read error (device disconnected?): {e}")
            self._healthy = False
            # Resetujemy stan do neutralnego OD RAZU, nie czekajac na
            # DeviceMonitor (ktory sprawdza is_healthy() dopiero co kilka
            # sekund) - inaczej get_state() zwracalaby zamrozone, ostatnie
            # wartosci osi (np. "pelny gaz do przodu") jeszcze przez caly ten
            # czas, a GamepadWorker napedzalby silniki tym zamrozonym stanem
            # zamiast je zatrzymac natychmiast po odlaczeniu pada.
            self._state = neutral_state(self.mapping)

    def _handle_event(self, event) -> None:
        if event.type == ecodes.EV_KEY:
            name = _resolve_mapped_name(ecodes.bytype[ecodes.EV_KEY], event.code, self.mapping)
            if name is not None:
                self._state.buttons[name] = bool(event.value)

        elif event.type == ecodes.EV_ABS:
            name = _resolve_mapped_name(ecodes.bytype[ecodes.EV_ABS], event.code, self.mapping)
            if name is None:
                return
            abs_min, abs_max = self._abs_ranges.get(event.code, (-1, 1))
            self._state.axes[name] = normalize_axis_value(event.value, abs_min, abs_max)
