import asyncio

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
    def __init__(self):
        self.calls = []

    def set_pwm(self, channel, on, off):
        self.calls.append((channel, on, off))


class DummySpeaker:
    def play(self, file_path):
        return True

    def stop(self):
        pass

    def get_state(self):
        return None


class DummyWs:
    async def send(self, message):
        pass


def make_processor(state, i2c_pwm=None):
    return CommandProcessor(
        command_queue=asyncio.Queue(),
        gpio=DummyGpio(),
        encoder=DummyEncoder(),
        i2c_pwm=i2c_pwm or DummyI2cPwm(),
        state=state,
        ws=DummyWs(),
        udp_frame_sender=DummyUdpFrameSender(),
        speaker=DummySpeaker(),
    )


def test_set_follow_band_mode_updates_state():
    async def run_test():
        state = RobotState()
        processor = make_processor(state)
        processor.command_queue.put_nowait({"type": "set_follow_band_mode", "enabled": True})

        await processor.process_commands()

        assert state.follow_band_mode is True

    asyncio.run(run_test())


def test_set_follow_band_speed_updates_state_and_clamps():
    async def run_test():
        state = RobotState()
        processor = make_processor(state)
        processor.command_queue.put_nowait({"type": "set_follow_band_speed", "pwm": 9000})

        await processor.process_commands()

        assert state.follow_band_max_pwm == 4095

    asyncio.run(run_test())


def test_manual_motor_command_ignored_while_following():
    async def run_test():
        state = RobotState(follow_band_mode=True)
        i2c_pwm = DummyI2cPwm()
        processor = make_processor(state, i2c_pwm=i2c_pwm)
        processor.command_queue.put_nowait({"type": "motor", "channel": 0, "pwm": 2000})

        await processor.process_commands()

        assert i2c_pwm.calls == []
        assert processor.wheel_channel_state == {}

    asyncio.run(run_test())


def test_manual_motor_command_applied_when_not_following():
    async def run_test():
        state = RobotState(follow_band_mode=False)
        i2c_pwm = DummyI2cPwm()
        processor = make_processor(state, i2c_pwm=i2c_pwm)
        processor.command_queue.put_nowait({"type": "motor", "channel": 0, "pwm": 2000})

        await processor.process_commands()

        assert i2c_pwm.calls == [(0, 0, 2000)]
        assert processor.wheel_channel_state == {0: 2000}

    asyncio.run(run_test())
