import asyncio

from ..hardware.gpio.gpio_controller import GPIOController
from ..hardware.i2c.i2c_pwm import i2cPWM
from ..robot_state import RobotState

class CommandProcessor:
    def __init__(self, command_queue: asyncio.Queue, gpio: GPIOController, i2c_pwm: i2cPWM, state: RobotState):
        self.command_queue: asyncio.Queue = command_queue
        self.gpio: GPIOController = gpio
        self.i2c_pwm: i2cPWM = i2c_pwm
        self.state: RobotState = state

    async def run(self):
        while True:
            await self.process_commands()
            await asyncio.sleep(0.005)

    async def process_commands(self):
        try:
            while True:
                cmd = self.command_queue.get_nowait()

                if cmd["type"] == "gpio":
                    if cmd["pin_name"] in self.gpio.pins:
                        self.gpio.set_named_pin(cmd["pin_name"], cmd["value"])
                    elif cmd["pin_name"] in self.gpio.standard_pins:
                        self.gpio.set_standard_pin(cmd["pin_name"], cmd["value"])
                    else:
                        print(f"Unknown pin name: {cmd['pin_name']}")

                elif cmd["type"] == "motor":
                    self.i2c_pwm.set_pwm(cmd["channel"], 0, cmd["pwm"])

                elif cmd["type"] == "stream":
                    self.state.stream_enabled = cmd["enabled"]

        except asyncio.QueueEmpty:
            pass