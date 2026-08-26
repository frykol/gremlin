import json

from websockets.asyncio.server import serve


class WsServer:
    def __init__(self, host, port, instruction_tab):
        self.host = host
        self.port = port
        self.instruction_tab = instruction_tab
        self._connection = None
        self._server = None

    async def connect(self):
        self._server = await serve(self._handler, self.host, self.port)
        await self._server.serve_forever()

    async def _handler(self, websocket):
        if self._connection is not None:
            try:
                await self._connection.close(reason="replaced by new connection")
            except Exception:
                pass

        self._connection = websocket

        try:
            async for message in websocket:
                json_message = json.loads(message)
                if json_message.get("type") == "register_video_sink":
                    json_message["host"] = websocket.remote_address[0]
                await self.instruction_tab.put(json_message)
        finally:
            if self._connection is websocket:
                self._connection = None

    async def send(self, message):
        if self._connection is None:
            print("Websocket not connected")
            return
        await self._connection.send(message)

    async def close(self):
        if self._connection is not None:
            try:
                await self._connection.close()
            except Exception:
                pass
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
