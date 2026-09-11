"""GamepadWorker musi (a) przezyc pojedynczy blad odczytu z gamepada -
patrz ten sam problem naprawiony w CameraWorker/LidarWorker/MicWorker
(tests/test_worker_read_error_resilience.py) - i (b) wysylac stan do
gamepad_ws TYLKO gdy sie faktycznie zmienil, zeby nie zasypywac trzeciej
aplikacji identycznymi wiadomosciami przy kazdej iteracji petli."""

import asyncio
import json

from src.hardware.gamepad.interface import GamepadState
from src.logic.follow_band import compute_drive_pwm
from src.robot_state import RobotState
from src.workers.gamepad_worker import GamepadWorker

MOTOR_PAIRS = {"FL": (0, 1), "FR": (3, 2), "RL": (4, 5), "RR": (7, 6)}


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


class RecordingI2cPwm:
    def __init__(self):
        self.calls = []

    def set_pwm(self, channel, on, off):
        self.calls.append((channel, off))


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


def test_gamepad_worker_drives_motors_when_forward_axis_changes():
    async def scenario():
        # left_stick_y = -1.0 (galka pchnieta w gore) -> vy = +1.0 (do przodu)
        states = [
            GamepadState(buttons={}, axes={"left_stick_y": 0.0, "right_stick_x": 0.0}),
            GamepadState(buttons={}, axes={"left_stick_y": -1.0, "right_stick_x": 0.0}),
        ]
        gamepad = ScriptedGamepad(states)
        i2c_pwm = RecordingI2cPwm()
        state = RobotState()
        worker = GamepadWorker(
            gamepad=gamepad,
            state=state,
            gamepad_ws=RecordingWs(),
            i2c_pwm=i2c_pwm,
            motor_pairs=MOTOR_PAIRS,
            drive_max_pwm=1000,
            poll_interval=0.001,
        )

        await _run_worker_briefly(worker, duration=0.05)

        expected = compute_drive_pwm(1.0, 0.0, 1000, MOTOR_PAIRS)
        driven = dict(i2c_pwm.calls)
        for channel, pwm in expected.items():
            assert driven[channel] == pwm

    asyncio.run(scenario())


def test_gamepad_worker_ignores_gamepad_when_follow_band_mode_active():
    async def scenario():
        states = [
            GamepadState(buttons={}, axes={"left_stick_y": 0.0, "left_stick_x": 0.0}),
            GamepadState(buttons={}, axes={"left_stick_y": -1.0, "left_stick_x": 0.0}),
        ]
        gamepad = ScriptedGamepad(states)
        i2c_pwm = RecordingI2cPwm()
        state = RobotState()
        state.follow_band_mode = True
        worker = GamepadWorker(
            gamepad=gamepad,
            state=state,
            gamepad_ws=RecordingWs(),
            i2c_pwm=i2c_pwm,
            motor_pairs=MOTOR_PAIRS,
            drive_max_pwm=1000,
            poll_interval=0.001,
        )

        await _run_worker_briefly(worker, duration=0.05)

        assert i2c_pwm.calls == []

    asyncio.run(scenario())


def test_gamepad_worker_bumper_r_raises_speed_limit_up_to_cap():
    async def scenario():
        # bumper_r wcisniety w kolejnych stanach - kazde nowe wcisniecie
        # (edge False->True) ma podniesc limit o step, ale nie ponad cap.
        states = [
            GamepadState(buttons={"bumper_r": False}, axes={}),
            GamepadState(buttons={"bumper_r": True}, axes={}),
            GamepadState(buttons={"bumper_r": False}, axes={}),
            GamepadState(buttons={"bumper_r": True}, axes={}),
        ]
        gamepad = ScriptedGamepad(states)
        i2c_pwm = RecordingI2cPwm()
        state = RobotState()
        worker = GamepadWorker(
            gamepad=gamepad,
            state=state,
            gamepad_ws=RecordingWs(),
            i2c_pwm=i2c_pwm,
            motor_pairs=MOTOR_PAIRS,
            drive_max_pwm=1900,
            drive_max_pwm_cap=2000,
            drive_max_pwm_step=100,
            poll_interval=0.001,
        )

        await _run_worker_briefly(worker, duration=0.08)

        # 1900 -> +100 (pierwsze wcisniecie) -> 2000 -> +100 (drugie
        # wcisniecie) ale przycieta do cap=2000, nie 2100.
        assert worker.current_max_pwm == 2000

    asyncio.run(scenario())


def test_gamepad_worker_bumper_l_lowers_speed_limit_down_to_zero():
    async def scenario():
        states = [
            GamepadState(buttons={"bumper_l": False}, axes={}),
            GamepadState(buttons={"bumper_l": True}, axes={}),
        ]
        gamepad = ScriptedGamepad(states)
        i2c_pwm = RecordingI2cPwm()
        state = RobotState()
        worker = GamepadWorker(
            gamepad=gamepad,
            state=state,
            gamepad_ws=RecordingWs(),
            i2c_pwm=i2c_pwm,
            motor_pairs=MOTOR_PAIRS,
            drive_max_pwm=50,
            drive_max_pwm_step=100,
            poll_interval=0.001,
        )

        await _run_worker_briefly(worker)

        assert worker.current_max_pwm == 0

    asyncio.run(scenario())


def test_gamepad_worker_trigger_l_boosts_speed_without_exceeding_cap():
    async def scenario():
        states = [
            GamepadState(buttons={"trigger_l": False}, axes={"left_stick_y": -1.0}),
            GamepadState(buttons={"trigger_l": True}, axes={"left_stick_y": -1.0}),
        ]
        gamepad = ScriptedGamepad(states)
        i2c_pwm = RecordingI2cPwm()
        state = RobotState()
        worker = GamepadWorker(
            gamepad=gamepad,
            state=state,
            gamepad_ws=RecordingWs(),
            i2c_pwm=i2c_pwm,
            motor_pairs=MOTOR_PAIRS,
            drive_max_pwm=1900,
            drive_max_pwm_cap=2000,
            drive_boost_pwm=150,
            poll_interval=0.001,
        )

        await _run_worker_briefly(worker, duration=0.05)

        # Boost (1900+150=2050) musi zostac przyciety do cap=2000, a nie
        # trwale podniesc current_max_pwm ponad wartosc bazowa.
        expected = compute_drive_pwm(1.0, 0.0, 2000, MOTOR_PAIRS)
        driven = dict(i2c_pwm.calls)
        for channel, pwm in expected.items():
            assert driven[channel] == pwm
        assert worker.current_max_pwm == 1900

    asyncio.run(scenario())


def test_gamepad_worker_skips_driving_when_no_i2c_pwm_configured():
    async def scenario():
        # Bez i2c_pwm/motor_pairs (domyslne None) worker musi dzialac tak
        # jak przed dodaniem sterowania - tylko odczyt/wysylka, bez proby
        # sterowania silnikami.
        gamepad = ScriptedGamepad([GamepadState(buttons={}, axes={"left_stick_y": -1.0})])
        state = RobotState()
        worker = GamepadWorker(gamepad=gamepad, state=state, gamepad_ws=RecordingWs(), poll_interval=0.001)

        await _run_worker_briefly(worker)

        assert state.gamepad_state is not None

    asyncio.run(scenario())
