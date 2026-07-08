import os
import shutil
import subprocess
from typing import Optional

from .interface import SdCardInterface


class SdCardReader(SdCardInterface):
    def __init__(self, device: str = "/dev/mmcblk1p1", mount_point: str = "/mnt/sdcard"):
        self.device: str = device
        self.mount_point: str = mount_point

        self.running: bool = False
        self._mounted_by_us: bool = False

    def start(self) -> None:
        if self.running:
            return

        os.makedirs(self.mount_point, exist_ok=True)

        if not os.path.ismount(self.mount_point):
            subprocess.run(["mount", self.device, self.mount_point], check=True)
            self._mounted_by_us = True

        self.running = True
        print("Czytnik kart SD (HW-125) działa")

    def stop(self) -> None:
        self.running = False

        if self._mounted_by_us:
            subprocess.run(["umount", self.mount_point], check=False)
            self._mounted_by_us = False

        print("Czytnik kart SD (HW-125) zatrzymany")

    def write_file(self, relative_path: str, data: bytes) -> bool:
        if not self.running:
            return False

        full_path = os.path.join(self.mount_point, relative_path)
        parent_dir = os.path.dirname(full_path)

        try:
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            with open(full_path, "wb") as file:
                file.write(data)

            return True
        except OSError:
            return False

    def read_file(self, relative_path: str) -> Optional[bytes]:
        if not self.running:
            return None

        full_path = os.path.join(self.mount_point, relative_path)

        try:
            with open(full_path, "rb") as file:
                return file.read()
        except OSError:
            return None

    def get_free_space_bytes(self) -> int:
        if not self.running:
            return 0

        return shutil.disk_usage(self.mount_point).free
