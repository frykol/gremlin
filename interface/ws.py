import asyncio
import websockets

connected = set()

async def handler(websocket):
    connected.add(websocket)
    print("Raspberry Pi się połączyło")

    try:
        # wysyłamy hello world od razu po połączeniu
        await websocket.send("hello world")

        async for message in websocket:
            print("Odebrano:", message)

            if message == "ping":
                await websocket.send("pong")
            else:
                await websocket.send("ok")

    finally:
        connected.remove(websocket)
        print("Połączenie zamknięte")

async def main():
    async with websockets.serve(handler, "0.0.0.0", 8765):
        print("Serwer działa na porcie 8765")
        await asyncio.Future()

asyncio.run(main())