import time
from smbus2 import SMBus

ADDR = 0x40
MODE1 = 0x00
PRESCALE = 0xFE
LED0 = 0x06

class i2cPWM:
    def __init__(self):
        self.started = False 
        self.bus = None

    def start(self) -> None:
        if self.started:
            return 
        self.bus = SMBus(1)
        self.bus.write_byte_data(ADDR, MODE1, 0x00)
        prescale = int(25000000.0 / 4096 / 50 - 1) 

        oldmode = self.bus.read_byte_data(ADDR, MODE1)
        sleep = (oldmode & 0x7F) | 0x10
        
        self.bus.write_byte_data(ADDR, MODE1, sleep)
        self.bus.write_byte_data(ADDR, PRESCALE, prescale)
        self.bus.write_byte_data(ADDR, MODE1, oldmode)

        time.sleep(0.005)

        self.bus.write_byte_data(ADDR, MODE1, oldmode | 0x80)

        self.started = True

    def set_pwm(self, ch, on, off) -> None:
        if not self.started:
            return 

        reg = LED0 + 4 * ch

        self.bus.write_byte_data(ADDR, reg, on & 0xFF)
        self.bus.write_byte_data(ADDR, reg + 1, on >> 8)
        self.bus.write_byte_data(ADDR, reg + 2, off & 0xFF) 
        self.bus.write_byte_data(ADDR, reg + 3, off >> 8)

    def set_pwm_percent(self, ch: int, percent: float):
        if not self.started:
            return
        
        percent = max(0, min(100,percent))
        off = int(4095 * percent / 100)
        self.set_pwm(ch, 0, off)