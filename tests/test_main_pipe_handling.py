import asyncio
import json

from src.main import _write_instruction_to_child


class BrokenPipeWriter:
    def write(self, _data):
        raise BrokenPipeError("broken pipe")

    def flush(self):
        pass


class RecordingWriter:
    def __init__(self):
        self.lines = []

    def write(self, data):
        self.lines.append(data)

    def flush(self):
        pass


def test_write_instruction_to_child_handles_broken_pipe():
    stopped = []

    async def fake_stop():
        stopped.append("stopped")

    async def run_test():
        pm_state = {
            "proc": type("Proc", (), {"returncode": None})(),
            "cmd_writer": BrokenPipeWriter(),
        }

        result = await _write_instruction_to_child(pm_state, {"type": "test"}, fake_stop)
        assert result is False
        assert stopped == ["stopped"]

    asyncio.run(run_test())


def test_write_instruction_to_child_writes_register_video_sink_message():
    """Regression guard for the replay mechanism's building block: writing a
    register_video_sink-shaped message to the child pipe must serialize the
    full message (including host/port) exactly as handed to it."""
    stopped = []

    async def fake_stop():
        stopped.append("stopped")

    async def run_test():
        writer = RecordingWriter()
        pm_state = {
            "proc": type("Proc", (), {"returncode": None})(),
            "cmd_writer": writer,
        }
        sink_msg = {"type": "register_video_sink", "host": "192.168.1.50", "port": 5555}

        result = await _write_instruction_to_child(pm_state, sink_msg, fake_stop)

        assert result is True
        assert stopped == []
        assert len(writer.lines) == 1
        assert json.loads(writer.lines[0]) == sink_msg

    asyncio.run(run_test())


def test_replay_cached_video_sink_to_freshly_started_child():
    """Simulates the exact replay step added to start_program_manager: once
    pm_state has a cached last_video_sink and a fresh child's cmd_writer is in
    place, replaying it must deliver the cached message to that child."""

    async def fake_stop():
        pass

    async def run_test():
        writer = RecordingWriter()
        pm_state = {
            "proc": type("Proc", (), {"returncode": None})(),
            "cmd_writer": writer,
            "tasks": [],
            "last_get_status": None,
            "last_video_sink": {"type": "register_video_sink", "host": "10.0.0.9", "port": 6000},
        }

        # Mirrors the replay block appended at the end of start_program_manager.
        if pm_state.get("last_video_sink") is not None:
            result = await _write_instruction_to_child(
                pm_state, pm_state["last_video_sink"], fake_stop
            )
            assert result is True

        assert len(writer.lines) == 1
        assert json.loads(writer.lines[0]) == pm_state["last_video_sink"]

    asyncio.run(run_test())
