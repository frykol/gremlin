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
