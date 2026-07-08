import json
import asyncio
from websockets.asyncio.client import connect, ClientConnection
from .interface import WSClientInterface

class WSClient(WSClientInterface):
    def __init__(self, uri, instruction_tab):
        self.uri = uri
        self.websocket: ClientConnection | None = None
        self.instruction_tab = instruction_tab

    async def connect(self):
        while True:
            try:
                print("Connecting...")

                self.websocket = await connect(self.uri)

                print("Connected")

                await self.websocket.send(json.dumps({
                    "type": "register",
                    "role": "robot"
                }))

                await self.listen()

            except Exception as e:
                print(f"WS disconnected: {e}")

            await asyncio.sleep(2)

    async def send(self, message):
        if self.websocket is None:
            print("Websocket not connected")
            return
        await self.websocket.send(message)

    async def listen(self):
        if not self.websocket:
            return
        
        async for message in self.websocket:
            json_message = json.loads(message)
            await self.instruction_tab.put(json_message)

    async def close(self):
        if self.websocket:
            await self.websocket.close()
