"""Gdy realny pad znika w trakcie dzialania (np. wyjety kabel USB), _read_loop
lapie wyjatek z evdev i musi NATYCHMIAST zresetowac stan do neutralnego -
inaczej GamepadWorker napedzalby silniki ostatnim znanym (np. "pelny gaz")
stanem az do najblizszego cyklu DeviceMonitor (domyslnie co kilka sekund),
co moze zaciac/uszkodzic robota. Wymaga zainstalowanego evdev (jest w
requirements.txt, obecne na docelowym RPi)."""

import asyncio

from src.hardware.gamepad.gamepad import Gamepad


class RaisingDevice:
    async def async_read_loop(self):
        raise OSError("device disconnected")
        yield  # pragma: no cover - nigdy nie osiagane, robi z tego async generator


def test_read_loop_resets_state_to_neutral_on_disconnect():
    async def scenario():
        loop = asyncio.get_running_loop()
        mapping = {"BTN_SOUTH": "a", "ABS_X": "left_stick_x"}
        gp = Gamepad(mapping=mapping, loop=loop)
        gp.device = RaisingDevice()
        gp._healthy = True
        gp._state.buttons["a"] = True
        gp._state.axes["left_stick_x"] = 1.0

        await gp._read_loop()

        assert gp.is_healthy() is False
        state = gp.get_state()
        assert state.buttons == {"a": False}
        assert state.axes == {"left_stick_x": 0.0}

    asyncio.run(scenario())
