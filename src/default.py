import asyncio

from .hardware.oak_d.factory import create_camera
from .hardware.i2c.factory import create_i2c_pwm
from .hardware.gpio.gpio_controller import GPIOController
from .hardware.gpio.encoder_controller import EncoderController
from .hardware.respeaker.factory import create_mic_array
from .hardware.sd_card.factory import create_sd_card
from .hardware.ads1115.factory import create_ads1115
from .hardware.lidar.factory import create_lidar
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
        "ws://192.168.1.249:8777",
        r_tab
    )

    asyncio.create_task(ws.connect())
    await asyncio.sleep(1)

    oak_d_camera = create_camera(config)

    mic_array = create_mic_array(config)
    sd_card = create_sd_card(config)
    ads1115 = create_ads1115(config)
    lidar = create_lidar(config)

    gpio_c = GPIOController()
    gpio_c.setup()

    gpio_config = config.get("gpio", {})
    encoder_c = EncoderController(
        chip=gpio_config.get("chip", "/dev/gpiochip0"),
        encoders=gpio_config.get("encoders", {}),
    )
    encoder_c.setup()

    i2c_p = create_i2c_pwm(config)
    i2c_p.start()

    _robot = RobotController(
        config=config,
        command_queue=r_tab,
        gpio=gpio_c,
        encoder=encoder_c,
        i2c_pwm=i2c_p,
        camera=oak_d_camera,
        mic_array=mic_array,
        sd_card=sd_card,
        ads1115=ads1115,
        lidar=lidar,
        ws=ws
    )


async def loop(config: dict) -> None:
    if _robot is None:
        raise RuntimeError("init(config) musi zostać wywołane przed loop(config)")

    await _robot.run()


