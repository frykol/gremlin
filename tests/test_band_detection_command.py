import asyncio
import json

from src.services.command_processor import CommandProcessor
from src.robot_state import BandDetectionState, RobotState


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


class RecordingWs:
    def __init__(self):
        self.sent = []

    async def send(self, message):
        self.sent.append(json.loads(message))


def test_get_band_detection_state_sends_current_state_over_ws():
    async def run_test():
        queue = asyncio.Queue()
        ws = RecordingWs()
        state = RobotState()
        state.band_detection_state = BandDetectionState(
            both_detected=True, left=True, right=True, last_update=123.0
        )
        processor = CommandProcessor(
            command_queue=queue,
            gpio=DummyGpio(),
            encoder=DummyEncoder(),
            i2c_pwm=DummyI2cPwm(),
            state=state,
            ws=ws,
            udp_frame_sender=DummyUdpFrameSender(),
        )

        queue.put_nowait({"type": "get_band_detection_state"})
        await processor.process_commands()

        assert ws.sent == [{
            "type": "band_detection_state",
            "both_detected": True,
            "left": True,
            "right": True,
            "last_update": 123.0,
            "debug_frame": "",
        }]

    asyncio.run(run_test())
