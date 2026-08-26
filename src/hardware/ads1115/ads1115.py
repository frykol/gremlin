import time
from typing import List, Tuple

from smbus2 import SMBus

from .interface import ADS1115Interface

CONVERSION_REG = 0x00
CONFIG_REG = 0x01

MUX_SINGLE_ENDED = [0x4, 0x5, 0x6, 0x7]  # AIN0..AIN3 vs GND

PGA_FSR_VOLTS = {
    2 / 3: 6.144,
    1: 4.096,
    2: 2.048,
    4: 1.024,
    8: 0.512,
    16: 0.256,
}
PGA_BITS = {
    2 / 3: 0x0,
    1: 0x1,
    2: 0x2,
    4: 0x3,
    8: 0x4,
    16: 0x5,
}

DATA_RATE_BITS = {
    8: 0x0,
    16: 0x1,
    32: 0x2,
    64: 0x3,
    128: 0x4,
    250: 0x5,
    475: 0x6,
    860: 0x7,
}

PRZELICZNIK = 16.8 / 3.185

# Możliwe adresy ADS1115 zależnie od podłączenia pinu ADDR (GND/VDD/SDA/SCL).
CANDIDATE_ADDRESSES = [0x48, 0x49, 0x4A, 0x4B]


class ADS1115(ADS1115Interface):
    def __init__(
        self,
        bus: int = 2,
        address: int = 0x48,
        gain: float = 1,
        data_rate: int = 128,
    ):
        self.bus_num = bus
        self.address = address
        self.gain = gain
        self.data_rate = data_rate

        self._bus: SMBus | None = None
        self._lsb = PGA_FSR_VOLTS[gain] / 32768.0

    def start(self) -> None:
        if self._bus is not None:
            return
        self._bus = SMBus(self.bus_num)
        self.address = self._resolve_address()

    def _probe_address(self, address: int) -> bool:
        try:
            self._bus.read_i2c_block_data(address, CONFIG_REG, 2)
            return True
        except OSError:
            return False

    def _resolve_address(self) -> int:
        if self._probe_address(self.address):
            return self.address

        for candidate in CANDIDATE_ADDRESSES:
            if candidate == self.address:
                continue
            if self._probe_address(candidate):
                print(
                    f"ADS1115: brak odpowiedzi pod adresem {hex(self.address)} z config.json, "
                    f"wykryto urzadzenie pod adresem {hex(candidate)}"
                )
                return candidate

        raise RuntimeError(
            f"ADS1115: nie znaleziono urzadzenia pod zadnym z adresow "
            f"{[hex(self.address)] + [hex(a) for a in CANDIDATE_ADDRESSES if a != self.address]}"
        )

    def stop(self) -> None:
        if self._bus is not None:
            self._bus.close()
            self._bus = None

    def _read_raw(self, channel: int) -> int:
        if self._bus is None:
            raise RuntimeError("ADS1115 nie jest uruchomiony")

        config = (
            (1 << 15)
            | (MUX_SINGLE_ENDED[channel] << 12)
            | (PGA_BITS[self.gain] << 9)
            | (1 << 8)
            | (DATA_RATE_BITS[self.data_rate] << 5)
            | 0x0003
        )

        self._bus.write_i2c_block_data(
            self.address, CONFIG_REG, [(config >> 8) & 0xFF, config & 0xFF]
        )

        time.sleep(1.0 / self.data_rate + 0.001)

        data = self._bus.read_i2c_block_data(self.address, CONVERSION_REG, 2)
        raw = (data[0] << 8) | data[1]
        if raw > 0x7FFF:
            raw -= 0x10000

        return raw

    def read_channels(self) -> List[Tuple[float, float]]:
        voltages = []
        for channel in range(4):
            raw = self._read_raw(channel)
            raw_voltage = raw * self._lsb
            voltages.append((raw_voltage, raw_voltage * PRZELICZNIK))

        return voltages
