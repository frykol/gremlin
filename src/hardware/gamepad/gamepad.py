import asyncio
import concurrent.futures
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
        self._abs_ranges: dict[str, tuple[int, int]] = {}
        self._read_future: Optional[concurrent.futures.Future] = None
        self._healthy: bool = False

    def start(self) -> None:
        if self.device is not None:
            return

        self.device = find_gamepad_device()
        self._healthy = True

        for code, absinfo in self.device.capabilities().get(ecodes.EV_ABS, []):
            code_name = _resolve_code_name(ecodes.bytype[ecodes.EV_ABS], code)
            if code_name is not None:
                self._abs_ranges[code_name] = (absinfo.min, absinfo.max)

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
