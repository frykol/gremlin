import os
import json
import errno
import asyncio

from .interface import WSClientInterface


class PipeWSClient(WSClientInterface):
    def __init__(self, uri, instruction_tab) -> None:
        self.uri = uri
        self.instruction_tab = instruction_tab
        self.cmd_fd = int(os.environ.get("PIPE_CMD_FD", "-1"))
        self.resp_fd = int(os.environ.get("PIPE_RESP_FD", "-1"))
        self._cmd_file = None
        self._resp_file = None

    async def connect(self) -> None:
        try:
            if self.cmd_fd < 0 or self.resp_fd < 0:
                raise RuntimeError("PIPE_CMD_FD or PIPE_RESP_FD not set for PipeWSClient")

            # Open files in text mode, line-buffered
            self._cmd_file = os.fdopen(self.cmd_fd, "r", encoding="utf-8", buffering=1)
            self._resp_file = os.fdopen(self.resp_fd, "w", encoding="utf-8", buffering=1)

            asyncio.create_task(self.listen())

        except Exception as e:
            print(f"PipeWSClient.connect error: {e}")

    async def send(self, message) -> None:
        try:
            if not self._resp_file:
                print("PipeWSClient: response pipe not open")
                return
            if isinstance(message, bytes):
                message = message.decode("utf-8")
            self._resp_file.write(message.rstrip("\n") + "\n")
            self._resp_file.flush()
        except Exception as e:
            if isinstance(e, BrokenPipeError) or (
                isinstance(e, OSError) and getattr(e, "errno", None) in {errno.EPIPE, errno.EINVAL}
            ):
                print(f"PipeWSClient.send: response pipe closed ({e})")
                await self.close()
                return
            print(f"PipeWSClient.send error: {e}")

    async def listen(self) -> None:
        try:
            if not self._cmd_file:
                print("PipeWSClient: command pipe not open")
                return

            while True:
                # Blocking readline in thread to avoid blocking event loop
                line = await asyncio.to_thread(self._cmd_file.readline)
                if not line:
                    await asyncio.sleep(0.1)
                    continue
                try:
                    msg = json.loads(line)
                except Exception:
                    print(f"PipeWSClient: invalid json from pipe: {line}")
                    continue
                await self.instruction_tab.put(msg)

        except Exception as e:
            print(f"PipeWSClient.listen error: {e}")

    async def close(self) -> None:
        try:
            if self._cmd_file:
                self._cmd_file.close()
            if self._resp_file:
                self._resp_file.close()
        except Exception:
            pass
