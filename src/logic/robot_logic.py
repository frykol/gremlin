import asyncio

class RobotLogic:
    def __init__(self, gpio, i2c_pwm):
        self.gpio = gpio
        self.i2c_pwm = i2c_pwm

    def setup(self):
        self.gpio.set_pin("R_EN", True)
        self.gpio.set_pin("L_EN", True)

    async def run(self):
        self.setup()
        while True:
            self.i2c_pwm.set_pwm(0, 0, 2000)
            await asyncio.sleep(1)

            self.i2c_pwm.set_pwm(0, 0, 0)
            await asyncio.sleep(1)