import asyncio
import json

from src.services.command_processor import CommandProcessor
from src.robot_state import RobotState, VoiceRecognitionState


class DummyUdpFrameSender:
    def set_target(self, host, port):
        pass


class DummyGpio:
    pins = {}
    standard_pins = {}


class DummyEncoder:
    pass


class DummyI2cPwm:
    def set_pwm(self, channel, on, off):
        pass


class DummySpeaker:
    def play(self, file_path, volume=1.0):
        pass

    def stop(self):
        pass


class RecordingWs:
    def __init__(self):
        self.sent = []

    async def send(self, message):
        self.sent.append(json.loads(message))


def _make_processor(queue, ws, state):
    return CommandProcessor(
        command_queue=queue,
        gpio=DummyGpio(),
        encoder=DummyEncoder(),
        i2c_pwm=DummyI2cPwm(),
        state=state,
        ws=ws,
        udp_frame_sender=DummyUdpFrameSender(),
        speaker=DummySpeaker(),
    )


def test_get_voice_recognition_state_sends_current_state_over_ws():
    async def run_test():
        queue = asyncio.Queue()
        ws = RecordingWs()
        state = RobotState()
        state.voice_recognition_state = VoiceRecognitionState(
            last_text="do przodu",
            last_action="▲  DO PRZODU",
            last_update=123.0,
            history=[{"text": "do przodu", "action": "▲  DO PRZODU", "time": 123.0}],
        )
        processor = _make_processor(queue, ws, state)

        queue.put_nowait({"type": "get_voice_recognition_state"})
        await processor.process_commands()

        assert ws.sent == [{
            "type": "voice_recognition_state",
            "last_text": "do przodu",
            "last_action": "▲  DO PRZODU",
            "last_update": 123.0,
            "history": [{"text": "do przodu", "action": "▲  DO PRZODU", "time": 123.0}],
        }]

    asyncio.run(run_test())


def test_get_voice_recognition_state_handles_missing_state():
    async def run_test():
        queue = asyncio.Queue()
        ws = RecordingWs()
        state = RobotState()
        processor = _make_processor(queue, ws, state)

        queue.put_nowait({"type": "get_voice_recognition_state"})
        await processor.process_commands()

        assert ws.sent == [{
            "type": "voice_recognition_state",
            "last_text": "",
            "last_action": None,
            "last_update": 0.0,
            "history": [],
        }]

    asyncio.run(run_test())
