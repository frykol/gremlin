import asyncio

from .config import load_config
from .hardware.oak_d.oak_d import OakDCamera
from .hardware.oak_d.webcam_camera import WebcamCamera
from .hardware.i2c.i2c_pwm import i2cPWM
from .hardware.i2c.i2c_pwm_dummy import i2cPWMDummy
from .hardware.gpio.gpio_controller import GPIOController
from .hardware.gpio.gpio_dummy import GPIOControllerDummy
from .dev_connection.client_factory import create_client
from .dev_connection.client import WSClientInterface
from .robot_controller import RobotController


async def robot_run():
    config = load_config("config.json")
    laptop_mode = config.get("laptop_mode", False)
    is_dev = config["dev"]

    r_tab = asyncio.Queue()

    ws_uri = config.get("websocket_uri", "ws://192.168.31.86:8765")
    use_websocket = is_dev and not laptop_mode
    ws: WSClientInterface = create_client(use_websocket, ws_uri, r_tab)

    asyncio.create_task(ws.connect())
    await asyncio.sleep(1)

    if laptop_mode:
        webcam_config = config.get("webcam", {})
        camera = WebcamCamera(
            device=webcam_config.get("device", 0),
            width=webcam_config.get("width", 1280),
            height=webcam_config.get("height", 720),
            fps=webcam_config.get("fps", 30),
            flip=webcam_config.get("flip", True),
        )
        gpio_c = GPIOControllerDummy()
        gpio_c.setup()
        i2c_p = i2cPWMDummy()
        i2c_p.start()
    else:
        oak_d_config = config["oak_d"]
        camera = OakDCamera(
            oak_d_config["width"],
            oak_d_config["height"],
        )
        gpio_c = GPIOController()
        gpio_c.setup()
        i2c_p = i2cPWM()
        i2c_p.start()

    robot = RobotController(
        config=config,
        command_queue=r_tab,
        gpio=gpio_c,
        i2c_pwm=i2c_p,
        camera=camera,
        ws=ws,
        laptop_mode=laptop_mode,
    )

    await robot.run()


def main():
    asyncio.run(robot_run())


if __name__ == "__main__":
    main()
