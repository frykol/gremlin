from .interface import ADS1115Interface
from .dummy_ads1115 import FakeADS1115


def create_ads1115(config: dict) -> ADS1115Interface:
    ads_config = config.get("ads1115", {})

    bus = ads_config.get("bus", 2)
    address = ads_config.get("address", 0x48)
    gain = ads_config.get("gain", 1)
    data_rate = ads_config.get("data_rate", 128)
    is_dummy = ads_config.get("is_dummy", False)

    if not is_dummy:
        from .ads1115 import ADS1115

        return ADS1115(bus=bus, address=address, gain=gain, data_rate=data_rate)

    return FakeADS1115()
