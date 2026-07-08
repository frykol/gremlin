from .interface import SdCardInterface
from .sd_card import SdCardReader
from .dummy_sd_card import DummySdCardReader


def create_sd_card(config: dict) -> SdCardInterface:
    sd_card_config = config.get("sd_card", {})

    device = sd_card_config.get("device", "/dev/mmcblk1p1")
    mount_point = sd_card_config.get("mount_point", "/mnt/sdcard")
    is_dummy = sd_card_config.get("is_dummy", False)

    if is_dummy:
        return DummySdCardReader(device=device, mount_point=mount_point)

    return SdCardReader(device=device, mount_point=mount_point)
