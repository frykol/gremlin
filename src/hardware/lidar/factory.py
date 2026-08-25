from .interface import LidarInterface
from .dummy_lidar import DummyLidar


def create_lidar(config: dict) -> LidarInterface:
    lidar_config = config.get("lidar", {})

    is_dummy = lidar_config.get("is_dummy", False)

    if is_dummy:
        return DummyLidar()

    from .unitree_l1 import UnitreeL1Lidar

    return UnitreeL1Lidar(
        port=lidar_config.get("port", "/dev/ttyUSB0"),
        baud=lidar_config.get("baud", 2_000_000),
        range_min=lidar_config.get("range_min", 0.05),
        range_max=lidar_config.get("range_max", 30.0),
        intensity_max=lidar_config.get("intensity_max", 255),
    )
