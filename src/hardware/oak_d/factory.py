from .interface import CameraInterface
from .oak_d import OakDCamera
from .dummy_oak_d import FakeOakDCamera
from ..status_log import log_device_status

DEVICE_NAME = "OAK-D"


def create_camera(config: dict) -> CameraInterface:
    oak_d_config = config.get("oak_d", {})

    width = oak_d_config.get("width", 640)
    height = oak_d_config.get("height", 480)
    fps = oak_d_config.get("fps", 30)
    is_dummy = oak_d_config.get("is_dummy", False)

    if is_dummy:
        log_device_status(DEVICE_NAME, "SUCCESS - DUMMY")
        return FakeOakDCamera(width=width, height=height)

    try:
        camera = OakDCamera(width=width, height=height, fps=fps)
        # OakDCamera nie otwiera urzadzenia w __init__ - polaczenie z
        # rzeczywistym sprzetem nawiazuje sie dopiero w start(), wiec musimy
        # je wywolac tutaj, zeby w ogole wykryc brak/awarie kamery. start()
        # ma wewnetrzny guard na running, wiec ponowne wywolanie przez
        # CameraWorker.start() jest bezpieczne (no-op).
        camera.start()
    except Exception as e:
        log_device_status(DEVICE_NAME, "ERROR")
        print(f"Failed to initialize {DEVICE_NAME}: {e}")
        log_device_status(DEVICE_NAME, "ERROR - FALLBACK TO DUMMY")
        return FakeOakDCamera(width=width, height=height)

    log_device_status(DEVICE_NAME, "SUCCESS")
    return camera
