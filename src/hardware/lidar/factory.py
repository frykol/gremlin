from .interface import LidarInterface
from .dummy_lidar import DummyLidar
from ..status_log import log_device_status

DEVICE_NAME = "LIDAR"


def create_lidar(config: dict) -> LidarInterface:
    lidar_config = config.get("lidar", {})

    is_dummy = lidar_config.get("is_dummy", False)
    external_bridge = lidar_config.get("external_bridge", False)

    if is_dummy or external_bridge:
        log_device_status(DEVICE_NAME, "SUCCESS - DUMMY")
        return DummyLidar()

    from .unitree_l1 import UnitreeL1Lidar

    try:
        lidar = UnitreeL1Lidar(
            port=lidar_config.get("port", "/dev/ttyUSB0"),
            baud=lidar_config.get("baud", 2_000_000),
            range_min=lidar_config.get("range_min", 0.05),
            range_max=lidar_config.get("range_max", 30.0),
            intensity_max=lidar_config.get("intensity_max", 255),
        )
        # Port szeregowy otwiera sie dopiero w start(), nie w __init__ -
        # bez tego wywolania brak/awaria lidaru nigdy nie trafialaby do try.
        lidar.start()
    except Exception as e:
        log_device_status(DEVICE_NAME, "ERROR")
        print(f"Failed to initialize {DEVICE_NAME}: {e}")
        log_device_status(DEVICE_NAME, "ERROR - FALLBACK TO DUMMY")
        return DummyLidar()

    log_device_status(DEVICE_NAME, "SUCCESS")
    return lidar
