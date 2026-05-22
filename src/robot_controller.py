import asyncio
import json
import base64
import cv2

class RobotController:
    def __init__(self, command_queue, gpio, i2c_pwm, camera, ws):
        self.command_queue = command_queue
        self.gpio = gpio
        self.i2c_pwm = i2c_pwm
        self.camera = camera
        self.ws = ws
        self.stream_enabled = False

    def switch(self, ch, pwm):
        for i in range(0, 4):
            self.i2c_pwm.set_pwm(i, 0, 0)
        self.i2c_pwm.set_pwm(ch, 0, pwm)

    async def command_loop(self):
        while True:
            await self.process_commands()
            await asyncio.sleep(0.005)


    async def camera_stream_loop(self, fps: int = 15):
        delay = 1 / fps

        while True:
            if self.stream_enabled:
                await self.send_camera_frame()

            await asyncio.sleep(delay)

    async def logic_loop(self):
        while True:
            self.i2c_pwm.set_pwm(0, 0, 2000)
            await asyncio.sleep(1)
            self.i2c_pwm.set_pwm(0, 0, 0)
            await asyncio.sleep(1)
            await asyncio.sleep(0.1)

    async def run(self):
        tasks = [
            asyncio.create_task(self.command_loop()),
            asyncio.create_task(self.camera_stream_loop(fps=15)),
            asyncio.create_task(self.logic_loop()),
        ]

        try:
            await asyncio.gather(*tasks)

        finally:
            for task in tasks:
                task.cancel()

            for i in range(4):
                self.i2c_pwm.set_pwm(i, 0, 0)

            self.camera.stop()

    async def send_camera_frame(self):
        frame = self.camera.get_camera_frame()

        if frame is None:
            return

        ok, buffer = cv2.imencode(
            ".jpg",
            frame.image,
            [cv2.IMWRITE_JPEG_QUALITY, 70]
        )

        if not ok:
            return

        jpg_base64 = base64.b64encode(buffer).decode("utf-8")

        await self.ws.send(json.dumps({
            "type": "camera_frame",
            "image": jpg_base64,
            "timestamp": frame.timestamp,
            "width": frame.width,
            "height": frame.height,
            "frame_id": frame.frame_id
        }))

    async def process_commands(self):
        try:
            while True:
                cmd = self.command_queue.get_nowait()

                if cmd["type"] == "gpio":
                    self.gpio.set_pin(cmd["pin_name"], cmd["value"])

                elif cmd["type"] == "motor":
                    self.i2c_pwm.set_pwm(cmd["channel"], 0, cmd["pwm"])

                elif cmd["type"] == "stream":
                    self.stream_enabled = cmd["enabled"]

        except asyncio.QueueEmpty:
            pass