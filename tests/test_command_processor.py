import asyncio
import json

from src.services.command_processor import CommandProcessor
from src.robot_state import RobotState


class DummyUdpFrameSender:
    def __init__(self):
        self.calls = []

    def set_target(self, host, port):
        self.calls.append((host, port))


class DummyGpio:
    pins = {}
    standard_pins = {}


class DummyI2cPwm:
    def set_pwm(self, channel, on, off):
        pass


class DummyWs:
    async def send(self, message):
        pass


def test_register_video_sink_updates_udp_frame_sender_target():
    async def run_test():
        queue = asyncio.Queue()
        udp_frame_sender = DummyUdpFrameSender()
        processor = CommandProcessor(
            command_queue=queue,
            gpio=DummyGpio(),
            i2c_pwm=DummyI2cPwm(),
            state=RobotState(),
            ws=DummyWs(),
            udp_frame_sender=udp_frame_sender,
        )

        queue.put_nowait({"type": "register_video_sink", "host": "10.0.0.9", "port": 9000})
        await processor.process_commands()

        assert udp_frame_sender.calls == [("10.0.0.9", 9000)]

    asyncio.run(run_test())


def test_motor_command_updates_wheel_channel_state():
    async def run_test():
        queue = asyncio.Queue()
        processor = CommandProcessor(
            command_queue=queue,
            gpio=DummyGpio(),
            i2c_pwm=DummyI2cPwm(),
            state=RobotState(),
            ws=DummyWs(),
            udp_frame_sender=DummyUdpFrameSender(),
        )

        queue.put_nowait({"type": "motor", "channel": 3, "pwm": 1500})
        await processor.process_commands()

        assert processor.wheel_channel_state == {3: 1500}

    asyncio.run(run_test())


def test_write_wheel_state_writes_atomic_json(tmp_path):
    processor = CommandProcessor(
        command_queue=asyncio.Queue(),
        gpio=DummyGpio(),
        i2c_pwm=DummyI2cPwm(),
        state=RobotState(),
        ws=DummyWs(),
        udp_frame_sender=DummyUdpFrameSender(),
    )
    processor.wheel_channel_state = {0: 4095, 1: 0, 2: 1500}

    out_path = tmp_path / "wheel_state.json"
    processor.write_wheel_state(str(out_path))

    assert out_path.exists()
    assert not (tmp_path / "wheel_state.json.tmp").exists()

    data = json.loads(out_path.read_text())
    assert data["channels"] == {"0": 4095, "1": 0, "2": 1500}
    assert isinstance(data["t_mono"], float)
