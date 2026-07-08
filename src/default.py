import asyncio

from .hardware.oak_d.factory import create_camera
from .hardware.i2c.i2c_pwm import i2cPWM
from .hardware.gpio.gpio_controller import GPIOController
from .hardware.respeaker.factory import create_mic_array
from .hardware.sd_card.factory import create_sd_card
from .dev_connection.client_factory import create_client
from .dev_connection.client import WSClientInterface
from .robot_controller import RobotController

_robot: RobotController | None = None


async def init(config: dict) -> None:
    global _robot

    is_dev = config["dev"]

    r_tab = asyncio.Queue()

    ws: WSClientInterface = create_client(
        is_dev,
        "ws://192.168.1.162:8765",
        r_tab
    )

    asyncio.create_task(ws.connect())
    await asyncio.sleep(1)

    oak_d_camera = create_camera(config)

    mic_array = create_mic_array(config)
    sd_card = create_sd_card(config)

    gpio_c = GPIOController()
    gpio_c.setup()

    i2c_p = i2cPWM()
    i2c_p.start()

    _robot = RobotController(
        config=config,
        command_queue=r_tab,
        gpio=gpio_c,
        i2c_pwm=i2c_p,
        camera=oak_d_camera,
        mic_array=mic_array,
        sd_card=sd_card,
        ws=ws
    )


async def loop(config: dict) -> None:
    if _robot is None:
        raise RuntimeError("init(config) musi zostać wywołane przed loop(config)")

    await _robot.run()


