import asyncio
import json

from src.hardware.respeaker.dummy_respeaker import FakeReSpeakerMicArray
from src.services.command_processor import CommandProcessor
from src.robot_state import RobotState


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


def _make_processor(queue, ws, state, mic_array=None):
    return CommandProcessor(
        command_queue=queue,
        gpio=DummyGpio(),
        encoder=DummyEncoder(),
        i2c_pwm=DummyI2cPwm(),
        state=state,
        ws=ws,
        udp_frame_sender=DummyUdpFrameSender(),
        speaker=DummySpeaker(),
        mic_array=mic_array,
    )


def test_get_noise_profile_status_returns_defaults_without_mic_array():
    async def run_test():
        queue = asyncio.Queue()
        ws = RecordingWs()
        processor = _make_processor(queue, ws, RobotState(), mic_array=None)

        queue.put_nowait({"type": "get_noise_profile_status"})
        await processor.process_commands()

        assert ws.sent == [{"type": "noise_profile_status", "is_calibrating": False, "has_profile": False}]

    asyncio.run(run_test())


def test_start_calibration_updates_mic_array_and_replies_calibrating():
    async def run_test():
        queue = asyncio.Queue()
        ws = RecordingWs()
        mic_array = FakeReSpeakerMicArray()
        processor = _make_processor(queue, ws, RobotState(), mic_array=mic_array)

        queue.put_nowait({"type": "start_noise_profile_calibration"})
        await processor.process_commands()

        assert mic_array.get_noise_profile_status().is_calibrating is True
        assert ws.sent == [{"type": "noise_profile_status", "is_calibrating": True, "has_profile": False}]

    asyncio.run(run_test())


def test_stop_calibration_marks_profile_as_available():
    async def run_test():
        queue = asyncio.Queue()
        ws = RecordingWs()
        mic_array = FakeReSpeakerMicArray()
        processor = _make_processor(queue, ws, RobotState(), mic_array=mic_array)

        queue.put_nowait({"type": "start_noise_profile_calibration"})
        queue.put_nowait({"type": "stop_noise_profile_calibration"})
        await processor.process_commands()

        status = mic_array.get_noise_profile_status()
        assert status.is_calibrating is False
        assert status.has_profile is True
        assert ws.sent[-1] == {"type": "noise_profile_status", "is_calibrating": False, "has_profile": True}

    asyncio.run(run_test())


def test_reset_profile_clears_it():
    async def run_test():
        queue = asyncio.Queue()
        ws = RecordingWs()
        mic_array = FakeReSpeakerMicArray()
        processor = _make_processor(queue, ws, RobotState(), mic_array=mic_array)

        queue.put_nowait({"type": "start_noise_profile_calibration"})
        queue.put_nowait({"type": "stop_noise_profile_calibration"})
        queue.put_nowait({"type": "reset_noise_profile"})
        await processor.process_commands()

        status = mic_array.get_noise_profile_status()
        assert status.has_profile is False
        assert ws.sent[-1] == {"type": "noise_profile_status", "is_calibrating": False, "has_profile": False}

    asyncio.run(run_test())
