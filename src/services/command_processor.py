import base64
import json
import os
import asyncio
import time

from ..hardware.gpio.gpio_controller import GPIOController
from ..hardware.gpio.encoder_controller import EncoderController
from ..hardware.i2c.interface import I2CPWMInterface
from ..robot_state import RobotState
from ..dev_connection.interface import WSClientInterface

LOG_PATH = "sim.log"
WHEEL_STATE_PATH = "/tmp/wheel_state.json"

class CommandProcessor:
    def __init__(self, command_queue: asyncio.Queue, gpio: GPIOController, encoder: EncoderController, i2c_pwm: I2CPWMInterface, state: RobotState, ws: WSClientInterface, udp_frame_sender):
        self.command_queue: asyncio.Queue = command_queue
        self.gpio: GPIOController = gpio
        self.encoder: EncoderController = encoder
        self.i2c_pwm: I2CPWMInterface = i2c_pwm
        self.state: RobotState = state
        self.ws: WSClientInterface = ws
        self.udp_frame_sender = udp_frame_sender
        self.wheel_channel_state: dict[int, int] = {}

    async def run(self):
        while True:
            await self.process_commands()
            await asyncio.sleep(0.005)

    async def process_commands(self):
        try:
            while True:
                cmd = self.command_queue.get_nowait()
                # if cmd:
                #     print(cmd)

                if cmd.get("send") == "logs":
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
                    self.wheel_channel_state[cmd["channel"]] = cmd["pwm"]

                elif cmd.get("type") == "stream":
                    self.state.stream_enabled = cmd["enabled"]

                elif cmd.get("type") == "audio_stream":
                    self.state.audio_stream_enabled = cmd["enabled"]

                elif cmd.get("type") == "register_video_sink":
                    self.udp_frame_sender.set_target(cmd["host"], cmd["port"])

                elif cmd.get("type") == "get_lidar_points":
                    await self._send_lidar_points()

                elif cmd.get("type") == "get_encoder_ticks":
                    await self._send_encoder_ticks()

                elif cmd.get("type") == "reset_encoders":
                    self.encoder.reset(cmd.get("name"))
                    await self._send_encoder_ticks()

        except asyncio.QueueEmpty:
            pass

    async def _send_lidar_points(self) -> None:
        buffer = self.state.lidar_point_buffer
        points = buffer.get_points() if buffer is not None else []

        await self.ws.send(json.dumps({
            "type": "lidar_points",
            "points": points,
        }))

    async def _send_encoder_ticks(self) -> None:
        encoder_state = self.state.encoder_state
        ticks = encoder_state.ticks if encoder_state is not None else {}

        await self.ws.send(json.dumps({
            "type": "encoder_ticks",
            "ticks": ticks,
        }))

    async def _send_log(self) -> None:
        try:
            with open(LOG_PATH, "rb") as file:
                encoded = base64.b64encode(file.read()).decode("utf-8")
        except OSError:
            encoded = ""

        await self.ws.send(json.dumps({
            "type": "logs",
            "file": encoded,
        }))

    def write_wheel_state(self, path: str = WHEEL_STATE_PATH) -> None:
        """Zapisuje aktualny stan kanalow PWM uzywanych do napedu kol wraz
        ze znacznikiem czasu monotonicznego, do odczytu przez
        wheel_odometry_reader.py (robot_ws) w osobnym procesie. Zapis
        atomowy (plik tymczasowy + rename), zeby czytelnik nigdy nie
        zobaczyl niekompletnego JSON-a."""
        payload = {
            "t_mono": time.monotonic(),
            "channels": {str(ch): pwm for ch, pwm in self.wheel_channel_state.items()},
        }
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w") as f:
            json.dump(payload, f)
        os.replace(tmp_path, path)

    async def run_wheel_state_writer(self, path: str = WHEEL_STATE_PATH, interval: float = 0.075):
        while True:
            self.write_wheel_state(path)
            await asyncio.sleep(interval)