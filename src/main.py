import asyncio

from .config import load_config
from .hardware.oak_d.oak_d import OakDCamera
from .hardware.oak_d.webcam_camera import WebcamCamera
from .hardware.i2c.i2c_pwm import i2cPWM
from .hardware.gpio.gpio_controller import GPIOController
from .dev_connection.client_factory import create_client
from .dev_connection.client import WSClientInterface
from .robot_controller import RobotController
from .hardware.oak_d.interface import CameraInterface


def _detect_camera_type(config: dict) -> str:
    camera_type = config.get("camera", "auto")
    if camera_type != "auto":
        return camera_type
    try:
        import depthai as dai

        if dai.Device.getAllAvailableDevices():
            return "oak_d"
    except Exception:
        pass
    return "webcam"


def _create_camera(config: dict) -> CameraInterface:
    if _detect_camera_type(config) == "oak_d":
        oak_d_config = config.get("oak_d", {})
        return OakDCamera(
            width=oak_d_config.get("width", 1280),
            height=oak_d_config.get("height", 720),
            fps=oak_d_config.get("fps", 30),
        )
    webcam_config = config.get("webcam", {})
    return WebcamCamera(
        device=webcam_config.get("device", 0),
        width=webcam_config.get("width", 1280),
        height=webcam_config.get("height", 720),
        fps=webcam_config.get("fps", 30),
        flip=webcam_config.get("flip", True),
    )


async def robot_run():
    config = load_config("config.json")
    is_dev = config["dev"]

    r_tab = asyncio.Queue()

    ws_uri = config.get("websocket_uri", "ws://192.168.31.86:8765")
    ws: WSClientInterface = create_client(is_dev, ws_uri, r_tab)

    asyncio.create_task(ws.connect())
    await asyncio.sleep(1)

    camera = _create_camera(config)

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
    )

    await robot.run()


def main():
    asyncio.run(robot_run())


if __name__ == "__main__":
    main()
