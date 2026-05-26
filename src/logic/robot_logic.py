import asyncio
from ..hardware.gpio.gpio_controller import GPIOController
from ..hardware.i2c.i2c_pwm import i2cPWM

class RobotLogic:
    def __init__(self, gpio: GPIOController, i2c_pwm: i2cPWM):
        self.gpio: GPIOController = gpio
        self.i2c_pwm: i2cPWM = i2c_pwm

    def setup(self):
        self.gpio.set_named_pin("R_EN", True)
        self.gpio.set_named_pin("L_EN", True)

    async def run(self):
        self.setup()
        while True:
            self.i2c_pwm.set_pwm(0, 0, 2000)
            await asyncio.sleep(1)

            self.i2c_pwm.set_pwm(0, 0, 0)
            await asyncio.sleep(1)