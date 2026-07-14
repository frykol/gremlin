import asyncio
import json

from src.dev_connection.ws_server import WsServer


class FakeConnection:
    def __init__(self, messages):
        self._messages = list(messages)
        self.sent = []
        self.closed = False
        self.close_reason = None

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)

    async def send(self, message):
        self.sent.append(message)

    async def close(self, reason=None):
        self.closed = True
        self.close_reason = reason


def test_handler_forwards_messages_to_instruction_tab():
    async def run_test():
        instruction_tab = asyncio.Queue()
        server = WsServer("0.0.0.0", 8765, instruction_tab)

        conn = FakeConnection([json.dumps({"type": "gpio", "pin_name": "GPIO4", "value": 1})])
        await server._handler(conn)

        msg = instruction_tab.get_nowait()
        assert msg == {"type": "gpio", "pin_name": "GPIO4", "value": 1}

    asyncio.run(run_test())


def test_handler_closes_previous_connection_when_new_one_arrives():
    async def run_test():
        instruction_tab = asyncio.Queue()
        server = WsServer("0.0.0.0", 8765, instruction_tab)

        first = FakeConnection([])
        # Keep the first connection "active" by not letting its handler task
        # finish before the second one connects: call _handler for the first
        # without awaiting its message loop completion semantics — instead,
        # directly exercise the replace path by handling a first connection
        # in a background task that blocks on an event.
        block = asyncio.Event()

        class BlockingConnection(FakeConnection):
            def __aiter__(self):
                return self

            async def __anext__(self):
                await block.wait()
                raise StopAsyncIteration

        blocking_first = BlockingConnection([])
        first_task = asyncio.create_task(server._handler(blocking_first))
        await asyncio.sleep(0)  # let first_task register as the active connection

        second = FakeConnection([])
        await server._handler(second)

        assert blocking_first.closed is True
        assert blocking_first.close_reason == "replaced by new connection"

        block.set()
        await first_task

    asyncio.run(run_test())


def test_send_no_ops_when_nothing_connected():
    async def run_test():
        instruction_tab = asyncio.Queue()
        server = WsServer("0.0.0.0", 8765, instruction_tab)

        await server.send("hello")  # must not raise

    asyncio.run(run_test())


def test_send_delivers_to_active_connection():
    async def run_test():
        instruction_tab = asyncio.Queue()
        server = WsServer("0.0.0.0", 8765, instruction_tab)

        block = asyncio.Event()

        class BlockingConnection(FakeConnection):
            def __aiter__(self):
                return self

            async def __anext__(self):
                await block.wait()
                raise StopAsyncIteration

        conn = BlockingConnection([])
        handler_task = asyncio.create_task(server._handler(conn))
        await asyncio.sleep(0)  # let handler_task register as the active connection

        await server.send("hello")

        assert conn.sent == ["hello"]

        block.set()
        await handler_task

    asyncio.run(run_test())


def test_send_no_ops_after_connection_disconnects_naturally():
    async def run_test():
        instruction_tab = asyncio.Queue()
        server = WsServer("0.0.0.0", 8765, instruction_tab)

        conn = FakeConnection([])  # empty messages -> StopAsyncIteration immediately
        await server._handler(conn)

        # handler ran to completion (natural disconnect, no replacement);
        # the active connection should have been cleared
        await server.send("hello")  # must not raise

        assert conn.sent == []

    asyncio.run(run_test())
