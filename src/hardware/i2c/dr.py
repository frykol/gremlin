import time
import gpiod
from gpiod.line import Direction, Value
from smbus2 import SMBus

# ===== PCA9685 =====
ADDR = 0x40
MODE1 = 0x00
PRESCALE = 0xFE
LED0 = 0x06

bus = SMBus(1)

bus.write_byte_data(ADDR, MODE1, 0x00)

prescale = int(25000000.0 / 4096 / 50 - 1)

oldmode = bus.read_byte_data(ADDR, MODE1)
sleep = (oldmode & 0x7F) | 0x10

bus.write_byte_data(ADDR, MODE1, sleep)
bus.write_byte_data(ADDR, PRESCALE, prescale)
bus.write_byte_data(ADDR, MODE1, oldmode)

time.sleep(0.005)

bus.write_byte_data(ADDR, MODE1, oldmode | 0x80)

def set_pwm(ch, on, off):
    reg = LED0 + 4 * ch
    bus.write_byte_data(ADDR, reg, on & 0xFF)
    bus.write_byte_data(ADDR, reg + 1, on >> 8)
    bus.write_byte_data(ADDR, reg + 2, off & 0xFF)
    bus.write_byte_data(ADDR, reg + 3, off >> 8)

# ===== GPIO (EN) =====
R_EN = 5
L_EN = 6

R2_EN = 17 
L2_EN = 27
with gpiod.request_lines(
    "/dev/gpiochip0",
    consumer="ibt2-en",
    config={
        R_EN: gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.ACTIVE),
        L_EN: gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.ACTIVE),
        R2_EN: gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.ACTIVE),
        L2_EN: gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.ACTIVE),
    },
) as gpio:

    def enable():
        gpio.set_value(R_EN, Value.ACTIVE)
        gpio.set_value(L_EN, Value.ACTIVE)

    def disable():
        gpio.set_value(R_EN, Value.INACTIVE)
        gpio.set_value(L_EN, Value.INACTIVE)

    def forward(power=2000):
        set_pwm(0, 0, power)  # R_PWM
        set_pwm(1, 0, 0)      # L_PWM
        set_pwm(2, 0, 0)      # L_PWM
        set_pwm(3, 0, 0)      # L_PWM
    def forward2(power=2000):
        set_pwm(0, 0, 0)  # R_PWM
        set_pwm(1, 0, 0)      # L_PWM
        set_pwm(2, 0, power)      # L_PWM
        set_pwm(3, 0, 0)      # L_PWM

    def backward(power=2000):
        set_pwm(0, 0, 0)
        set_pwm(1, 0, power)
        set_pwm(2, 0, 0)      # L_PWM
        set_pwm(3, 0, 0)      # L_PWM

    def backward2(power=2000):
        set_pwm(0, 0, 0)
        set_pwm(1, 0, 0)
        set_pwm(2, 0, 0)      # L_PWM
        set_pwm(3, 0, power)      # L_PWM

    def stop():
        set_pwm(0, 0, 0)
        set_pwm(1, 0, 0)
        set_pwm(2, 0, 0)
        set_pwm(3, 0, 0)

    forward(4095)
    time.sleep(2)

    stop()
    time.sleep(1)

    backward(4095) 
    time.sleep(2)

    stop()
    forward2(4095)
    time.sleep(2)

    stop()

    backward2(4095)
    time.sleep(2)
    stop()
    print("END")
