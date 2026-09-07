import asyncio
import json

from src.hardware.respeaker.dummy_respeaker import FakeReSpeakerMicArray
from src.hardware.respeaker.interface import AudioFilterConfig
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


def test_get_audio_filter_config_returns_defaults_without_mic_array():
    async def run_test():
        queue = asyncio.Queue()
        ws = RecordingWs()
        processor = _make_processor(queue, ws, RobotState(), mic_array=None)

        queue.put_nowait({"type": "get_audio_filter_config"})
        await processor.process_commands()

        assert ws.sent == [{
            "type": "audio_filter_config",
            "lidar_center_hz": 192.5,
            "lidar_width_hz": 85.0,
            "lidar_enabled": True,
            "motor_center_hz": 415.0,
            "motor_width_hz": 110.0,
            "motor_enabled": True,
        }]

    asyncio.run(run_test())


def test_set_audio_filter_config_updates_mic_array_and_replies_with_new_state():
    async def run_test():
        queue = asyncio.Queue()
        ws = RecordingWs()
        mic_array = FakeReSpeakerMicArray()
        processor = _make_processor(queue, ws, RobotState(), mic_array=mic_array)

        queue.put_nowait({
            "type": "set_audio_filter_config",
            "lidar_width_hz": 10.0,
            "motor_enabled": False,
        })
        await processor.process_commands()

        updated = mic_array.get_filter_config()
        assert updated.lidar_width_hz == 10.0
        assert updated.motor_enabled is False
        # Untouched fields keep their previous values.
        assert updated.lidar_center_hz == 192.5
        assert updated.motor_center_hz == 415.0

        assert ws.sent == [{
            "type": "audio_filter_config",
            "lidar_center_hz": 192.5,
            "lidar_width_hz": 10.0,
            "lidar_enabled": True,
            "motor_center_hz": 415.0,
            "motor_width_hz": 110.0,
            "motor_enabled": False,
        }]

    asyncio.run(run_test())


def test_set_audio_filter_config_without_mic_array_is_a_noop():
    async def run_test():
        queue = asyncio.Queue()
        ws = RecordingWs()
        processor = _make_processor(queue, ws, RobotState(), mic_array=None)

        queue.put_nowait({"type": "set_audio_filter_config", "lidar_width_hz": 10.0})
        await processor.process_commands()

        assert ws.sent == [{
            "type": "audio_filter_config",
            "lidar_center_hz": 192.5,
            "lidar_width_hz": 85.0,
            "lidar_enabled": True,
            "motor_center_hz": 415.0,
            "motor_width_hz": 110.0,
            "motor_enabled": True,
        }]

    asyncio.run(run_test())
