import asyncio

from src.hardware.gpio.gpio_controller import GPIOController
from src.hardware.i2c.i2c_pwm import i2cPWM
from src.hardware.oak_d.factory import create_camera
from src.hardware.respeaker.factory import create_mic_array
from src.hardware.sd_card.factory import create_sd_card
from src.hardware.ads1115.factory import create_ads1115
from src.dev_connection.client_factory import create_client
from src.dev_connection.client import WSClientInterface
from src.robot_controller import RobotController

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
    ads1115 = create_ads1115(config)

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
        ads1115=ads1115,
        ws=ws
    )

    print("TEST 123")

    # tutaj mozesz dodac wlasna logike inicjalizacyjna


async def loop(config: dict) -> None:
    if _robot is None:
        raise RuntimeError("init(config) musi zostać wywołane przed loop(config)")

    await _robot.run()

    # tutaj mozesz dodac wlasna logike petli robota
