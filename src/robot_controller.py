import asyncio

from .hardware.oak_d.dummy_oak_d import FakeOakDCamera
from .hardware.oak_d.interface import CameraInterface
from .hardware.i2c.i2c_pwm import i2cPWM
from .hardware.gpio.gpio_controller import GPIOController

class RobotController:
    def __init__(self, command_queue, gpio: GPIOController, i2c_pwm: i2cPWM, camera: CameraInterface, ws):
        self.command_queue = command_queue
        self.gpio = gpio
        self.i2c_pwm = i2c_pwm
        self.camera = camera
        self.ws = ws

    def switch(self, ch, pwm):
        for i in range(0, 4):
            self.i2c_pwm.set_pwm(i, 0, 0)
        self.i2c_pwm.set_pwm(ch, 0, pwm)

    async def run(self):
        cnt = 0
        try:
            while True:
                await self.process_commands()
                
                self.switch(cnt, 2000)
                cnt += 1
                cnt %= 4
                await asyncio.sleep(2)
        finally:
            self.i2c_pwm.set_pwm(0,0,0)
            self.i2c_pwm.set_pwm(1,0,0)
            self.i2c_pwm.set_pwm(2,0,0)
            self.i2c_pwm.set_pwm(3,0,0)
            self.camera.stop()

    async def process_commands(self):
        try:
            while True:
                cmd = self.command_queue.get_nowait()

                if cmd["type"] == "gpio":
                    self.gpio.set_pin(cmd["pin_name"], cmd["value"])

                elif cmd["type"] == "motor":
                    self.i2c_pwm.set_pwm(cmd["channel"], 0, cmd["pwm"])

        except asyncio.QueueEmpty:
            pass
