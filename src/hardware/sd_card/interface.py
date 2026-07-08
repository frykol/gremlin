from abc import ABC, abstractmethod
from typing import Optional


class SdCardInterface(ABC):
    @abstractmethod
    def start(self) -> None:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass

    @abstractmethod
    def write_file(self, relative_path: str, data: bytes) -> bool:
        pass

    @abstractmethod
    def read_file(self, relative_path: str) -> Optional[bytes]:
        pass

    @abstractmethod
    def get_free_space_bytes(self) -> int:
        pass
