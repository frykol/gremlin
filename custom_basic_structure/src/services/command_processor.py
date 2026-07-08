import base64
import json
import asyncio

from ..hardware.gpio.gpio_controller import GPIOController
from ..hardware.i2c.i2c_pwm import i2cPWM
from ..robot_state import RobotState
from ..dev_connection.interface import WSClientInterface

LOG_PATH = "sim.log"

class CommandProcessor:
    def __init__(self, command_queue: asyncio.Queue, gpio: GPIOController, i2c_pwm: i2cPWM, state: RobotState, ws: WSClientInterface):
        self.command_queue: asyncio.Queue = command_queue
        self.gpio: GPIOController = gpio
        self.i2c_pwm: i2cPWM = i2c_pwm
        self.state: RobotState = state
        self.ws: WSClientInterface = ws

    async def run(self):
        while True:
            await self.process_commands()
            await asyncio.sleep(0.005)

    async def process_commands(self):
        try:
            while True:
                cmd = self.command_queue.get_nowait()

                if cmd.get("send") == "log":
                    await self._send_log()

                elif cmd.get("type") == "gpio":
                    if cmd["pin_name"] in self.gpio.pins:
                        self.gpio.set_named_pin(cmd["pin_name"], cmd["value"])
                    elif cmd["pin_name"] in self.gpio.standard_pins:
                        self.gpio.set_standard_pin(cmd["pin_name"], cmd["value"])
                    else:
                        print(f"Unknown pin name: {cmd['pin_name']}")

                elif cmd.get("type") == "motor":
                    self.i2c_pwm.set_pwm(cmd["channel"], 0, cmd["pwm"])

                elif cmd.get("type") == "stream":
                    self.state.stream_enabled = cmd["enabled"]

                elif cmd.get("type") == "audio_stream":
                    self.state.audio_stream_enabled = cmd["enabled"]

        except asyncio.QueueEmpty:
            pass

    async def _send_log(self) -> None:
        try:
            with open(LOG_PATH, "rb") as file:
                encoded = base64.b64encode(file.read()).decode("utf-8")
        except OSError:
            encoded = ""

        await self.ws.send(json.dumps({
            "type": "log",
            "file": encoded,
        }))