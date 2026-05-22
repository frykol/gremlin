import json
import time
import asyncio
import cv2
from .config import load_config
from .hardware.oak_d.dummy_oak_d import FakeOakDCamera
from .hardware.oak_d.oak_d import OakDCamera
from .hardware.i2c.i2c_pwm import i2cPWM
from .hardware.gpio.gpio_controller import GPIOController
from .dev_connection.client_factory import create_client
from .dev_connection.client import WSClientInterface
from .robot_controller import RobotController

def switch(i2c, ch, pwm):
    for i in range(0, 4):
       i2c.set_pwm(i,0,0)
    i2c.set_pwm(ch, 0, pwm)

async def loop():
    config = load_config("config.json")
    is_dev = config["dev"]

    r_tab = asyncio.Queue()

    ws: WSClientInterface = create_client(
        is_dev,
        "ws://192.168.31.86:8765",
        r_tab
    )

    asyncio.create_task(ws.connect())
    await asyncio.sleep(1)

    oak_d_config = config["oak_d"]
    oak_d_camera = OakDCamera(
        oak_d_config["width"],
        oak_d_config["height"]
    )

    oak_d_camera.start()

    gpio_c = GPIOController()
    gpio_c.setup()
    gpio_c.set_pin("R_EN", True)
    gpio_c.set_pin("L_EN", True)

    i2c_p = i2cPWM()
    i2c_p.start()

    robot = RobotController(
        command_queue=r_tab,
        gpio=gpio_c,
        i2c_pwm=i2c_p,
        camera=oak_d_camera,
        ws=ws
    )

    await robot.run()

def main():
    asyncio.run(loop())

if __name__ == "__main__":
    main()
