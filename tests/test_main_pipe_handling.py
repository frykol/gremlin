import asyncio

from src.main import _write_instruction_to_child


class BrokenPipeWriter:
    def write(self, _data):
        raise BrokenPipeError("broken pipe")

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
