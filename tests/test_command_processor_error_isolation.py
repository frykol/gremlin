import asyncio
import json

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


def test_a_command_that_raises_does_not_block_later_commands():
    """Regression: a set_audio_filter_config with a degenerate width used
    to raise inside process_commands()'s single while-loop, which only
    caught asyncio.QueueEmpty - so the exception escaped, and every
    command queued after it (from any tab: motors, GPIO, everything) was
    silently dropped for the rest of the process's life. process_commands
    must isolate each command so one bad command can't take the whole
    queue down with it."""
    async def run_test():
        queue = asyncio.Queue()
        ws = RecordingWs()
        state = RobotState()
        processor = _make_processor(queue, ws, state)

        # Missing "pin_name" makes the gpio handler raise a KeyError.
        queue.put_nowait({"type": "gpio", "value": 1})
        # This must still run even though the command above raised.
        queue.put_nowait({"type": "motor", "channel": 2, "pwm": 900})

        await processor.process_commands()

        assert processor.wheel_channel_state == {2: 900}

    asyncio.run(run_test())


def test_get_audio_filter_config_still_replies_after_a_prior_command_raised():
    async def run_test():
        queue = asyncio.Queue()
        ws = RecordingWs()
        state = RobotState()
        processor = _make_processor(queue, ws, state)

        queue.put_nowait({"type": "gpio", "value": 1})  # raises: missing pin_name
        queue.put_nowait({"type": "get_audio_filter_config"})

        await processor.process_commands()

        assert ws.sent[-1]["type"] == "audio_filter_config"

    asyncio.run(run_test())
