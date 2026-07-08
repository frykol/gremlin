import asyncio
from abc import ABC, abstractmethod

class WSClientInterface(ABC):
    @abstractmethod
    def __init__(self, uri, instruction_tab) -> None:
        pass

    @abstractmethod
    async def connect(self) -> None:
        pass

    @abstractmethod
    async def send(self, message) -> None:
        pass

    @abstractmethod
    async def listen(self) -> None:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass
