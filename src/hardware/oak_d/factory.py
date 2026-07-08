from .interface import CameraInterface
from .oak_d import OakDCamera
from .dummy_oak_d import FakeOakDCamera


def create_camera(config: dict) -> CameraInterface:
    oak_d_config = config.get("oak_d", {})

    width = oak_d_config.get("width", 640)
    height = oak_d_config.get("height", 480)
    fps = oak_d_config.get("fps", 30)
    is_dummy = oak_d_config.get("is_dummy", False)

    if is_dummy:
        return FakeOakDCamera(width=width, height=height)

    return OakDCamera(width=width, height=height, fps=fps)
