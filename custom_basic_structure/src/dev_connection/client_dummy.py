import asyncio
from .interface import WSClientInterface

class WSClientDummy(WSClientInterface):
    def __init__(self, uri, instruction_tab) -> None:
        pass

    async def connect(self) -> None:
        pass

    async def send(self, message) -> None:
        pass

    async def listen(self) -> None:
        pass

    async def close(self) -> None:
        pass
