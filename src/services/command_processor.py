import asyncio

class CommandProcessor:
    def __init__(self, command_queue, gpio, i2c_pwm, state):
        self.command_queue = command_queue
        self.gpio = gpio
        self.i2c_pwm = i2c_pwm
        self.state = state

    async def run(self):
        while True:
            await self.process_commands()
            await asyncio.sleep(0.005)

    async def process_commands(self):
        try:
            while True:
                cmd = self.command_queue.get_nowait()

                if cmd["type"] == "gpio":
                    self.gpio.set_pin(cmd["pin_name"], cmd["value"])

                elif cmd["type"] == "motor":
                    self.i2c_pwm.set_pwm(cmd["channel"], 0, cmd["pwm"])

                elif cmd["type"] == "stream":
                    self.state.stream_enabled = cmd["enabled"]

        except asyncio.QueueEmpty:
            pass