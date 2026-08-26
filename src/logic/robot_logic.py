import asyncio
from ..hardware.gpio.gpio_controller import GPIOController
from ..hardware.i2c.interface import I2CPWMInterface
from ..robot_state import RobotState

class RobotLogic:
    def __init__(self, gpio: GPIOController, i2c_pwm: I2CPWMInterface, state: RobotState):
        self.gpio: GPIOController = gpio
        self.i2c_pwm: I2CPWMInterface = i2c_pwm
        self.state: RobotState = state

    def setup(self):
        # self.gpio.set_named_pin("R_EN", True)
        # self.gpio.set_named_pin("L_EN", True)
        pass

    async def run(self):
        self.setup()
        while True:
            # self.i2c_pwm.set_pwm(0, 0, 2000)
            # await asyncio.sleep(1)

            # self.i2c_pwm.set_pwm(0, 0, 0)
            # await asyncio.sleep(1)
            await asyncio.sleep(0.1)