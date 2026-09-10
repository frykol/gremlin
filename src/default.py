import asyncio

from .hardware.oak_d.factory import create_camera
from .hardware.i2c.factory import create_i2c_pwm
from .hardware.gpio.gpio_controller import GPIOController
from .hardware.gpio.encoder_controller import EncoderController
from .hardware.respeaker.factory import create_mic_array
from .hardware.sd_card.factory import create_sd_card
from .hardware.ads1115.factory import create_ads1115
from .hardware.lidar.factory import create_lidar
from .hardware.speaker.factory import create_speaker
from .hardware.gamepad.factory import create_gamepad
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

    camera_slot = create_camera(config)

    mic_array_slot = create_mic_array(config)
    sd_card_slot = create_sd_card(config)
    ads1115_slot = create_ads1115(config)
    lidar_slot = create_lidar(config)
    speaker_slot = create_speaker(config)
    gamepad_slot = create_gamepad(config)

    gpio_c = GPIOController()
    gpio_c.setup()

    gpio_config = config.get("gpio", {})
    encoder_c = EncoderController(
        chip=gpio_config.get("chip", "/dev/gpiochip0"),
        encoders=gpio_config.get("encoders", {}),
    )
    encoder_c.setup()

    i2c_pwm_slot = create_i2c_pwm(config)

    _robot = RobotController(
        config=config,
        command_queue=r_tab,
        gpio=gpio_c,
        encoder=encoder_c,
        i2c_pwm=i2c_pwm_slot,
        camera=camera_slot,
        mic_array=mic_array_slot,
        sd_card=sd_card_slot,
        ads1115=ads1115_slot,
        lidar=lidar_slot,
        speaker=speaker_slot,
        gamepad=gamepad_slot,
        ws=ws
    )


async def loop(config: dict) -> None:
    if _robot is None:
        raise RuntimeError("init(config) musi zostać wywołane przed loop(config)")

    await _robot.run()


