import asyncio
import json

from src.services.command_processor import CommandProcessor
from src.robot_state import ColorDetectionState, RobotState


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


def test_get_color_detection_state_sends_current_state_over_ws():
    async def run_test():
        queue = asyncio.Queue()
        ws = RecordingWs()
        state = RobotState()
        state.color_detection_state = ColorDetectionState(
            detected=True, blue_ratio=0.42, last_update=123.0
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

        queue.put_nowait({"type": "get_color_detection_state"})
        await processor.process_commands()

        assert ws.sent == [{
            "type": "color_detection_state",
            "detected": True,
            "blue_ratio": 0.42,
            "last_update": 123.0,
            "debug_frame": "",
            "blue_bboxes": [],
            "yellow_bboxes": [],
            "target_bbox": None,
            "green_on_yellow_detected": False,
        }]

    asyncio.run(run_test())
