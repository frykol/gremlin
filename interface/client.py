import asyncio
import websockets

async def run():
    uri = "ws://192.168.31.134:8765"

    async with websockets.connect(uri) as websocket:
        print("Połączono z PC")

        msg = await websocket.recv()
        print("Serwer mówi:", msg)

        await websocket.send("ping")
        resp = await websocket.recv()
        print("Odp:", resp)

        while True:
            await asyncio.sleep(1)

asyncio.run(run())