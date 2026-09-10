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

        self._read_task = asyncio.get_running_loop().create_task(self._read_loop())
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
