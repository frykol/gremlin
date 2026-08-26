import unittest

from src.hardware.ads1115.ads1115 import ADS1115


class FakeBus:
    def __init__(self, responding_addresses):
        self.responding_addresses = set(responding_addresses)

    def read_i2c_block_data(self, address, register, length):
        if address not in self.responding_addresses:
            raise OSError(f"no device at {hex(address)}")
        return [0, 0]


class ADS1115AddressDetectionTest(unittest.TestCase):
    def test_uses_configured_address_when_it_responds(self):
        device = ADS1115(address=0x48)
        device._bus = FakeBus(responding_addresses=[0x48, 0x49])

        resolved = device._resolve_address()

        self.assertEqual(resolved, 0x48)

    def test_falls_back_to_candidate_when_configured_address_silent(self):
        device = ADS1115(address=0x48)
        device._bus = FakeBus(responding_addresses=[0x49])

        resolved = device._resolve_address()

        self.assertEqual(resolved, 0x49)

    def test_raises_when_no_candidate_responds(self):
        device = ADS1115(address=0x48)
        device._bus = FakeBus(responding_addresses=[])

        with self.assertRaises(RuntimeError):
            device._resolve_address()


if __name__ == "__main__":
    unittest.main()
