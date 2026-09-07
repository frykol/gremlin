from .interface import SdCardInterface
from .sd_card import SdCardReader
from .dummy_sd_card import DummySdCardReader
from ..status_log import log_device_status

DEVICE_NAME = "SD-CARD"


def create_sd_card(config: dict) -> SdCardInterface:
    sd_card_config = config.get("sd_card", {})

    device = sd_card_config.get("device", "/dev/mmcblk1p1")
    mount_point = sd_card_config.get("mount_point", "/mnt/sdcard")
    is_dummy = sd_card_config.get("is_dummy", False)

    if is_dummy:
        log_device_status(DEVICE_NAME, "SUCCESS - DUMMY")
        return DummySdCardReader(device=device, mount_point=mount_point)

    try:
        sd_card = SdCardReader(device=device, mount_point=mount_point)
        # Montowanie karty odbywa sie dopiero w start(), nie w __init__ -
        # bez tego wywolania brak/awaria karty nigdy nie trafialaby do try.
        sd_card.start()
    except Exception as e:
        log_device_status(DEVICE_NAME, "ERROR")
        print(f"Failed to initialize {DEVICE_NAME}: {e}")
        log_device_status(DEVICE_NAME, "ERROR - FALLBACK TO DUMMY")
        return DummySdCardReader(device=device, mount_point=mount_point)

    log_device_status(DEVICE_NAME, "SUCCESS")
    return sd_card
