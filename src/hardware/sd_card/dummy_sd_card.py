from typing import Optional

from .interface import SdCardInterface


class DummySdCardReader(SdCardInterface):
    def __init__(self, device: str = "/dev/mmcblk1p1", mount_point: str = "/mnt/sdcard"):
        self.device: str = device
        self.mount_point: str = mount_point

        self.running: bool = False
        self._files: dict[str, bytes] = {}

    def start(self) -> None:
        self.running = True
        print("Czytnik kart SD (HW-125, dummy) działa")

    def stop(self) -> None:
        self.running = False
        print("Czytnik kart SD (HW-125, dummy) zatrzymany")

    def write_file(self, relative_path: str, data: bytes) -> bool:
        if not self.running:
            return False

        self._files[relative_path] = data
        return True

    def read_file(self, relative_path: str) -> Optional[bytes]:
        if not self.running:
            return None

        return self._files.get(relative_path)

    def get_free_space_bytes(self) -> int:
        if not self.running:
            return 0

        return 1024 * 1024 * 1024
