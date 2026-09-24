import asyncio

from .interface import CameraInterface
from .oak_d import OakDCamera
from .dummy_oak_d import FakeOakDCamera
from ..status_log import log_device_status
from ..device_slot import DeviceSlot
from ..device_monitor import DeviceMonitor, start_device_monitor

DEVICE_NAME = "OAK-D"


def _build_dummy(config: dict) -> CameraInterface:
    oak_d_config = config.get("oak_d", {})
    width = oak_d_config.get("width", 640)
    height = oak_d_config.get("height", 480)
    camera = FakeOakDCamera(width=width, height=height)
    # DeviceMonitor podmienia instancje w slocie w trakcie dzialania robota -
    # CameraWorker.start() wola sie tylko raz, przy starcie calego robota,
    # wiec swiezy dummy musi sam sie wystartowac, inaczej get_camera_frame()
    # zwracaloby None w nieskonczonosc i podglad zamrazalby sie na ostatniej
    # klatce sprzed awarii.
    camera.start()
    return camera


def _build_real(config: dict) -> CameraInterface:
    oak_d_config = config.get("oak_d", {})
    width = oak_d_config.get("width", 640)
    height = oak_d_config.get("height", 480)
    fps = oak_d_config.get("fps", 30)

    # OakDCamera nie otwiera urzadzenia w __init__ - polaczenie z rzeczywistym
    # sprzetem nawiazuje sie dopiero w start(), wiec musimy je wywolac tutaj,
    # zeby w ogole wykryc brak/awarie kamery. start() ma wewnetrzny guard na
    # running, wiec ponowne wywolanie przez CameraWorker.start() jest
    # bezpieczne (no-op).
    camera = OakDCamera(width=width, height=height, fps=fps)
    camera.start()
    return camera


def create_camera(config: dict) -> DeviceSlot:
    oak_d_config = config.get("oak_d", {})
    is_dummy = oak_d_config.get("is_dummy", False)
    poll_interval = config.get("device_health_check_interval", 5.0)

    if is_dummy:
        log_device_status(DEVICE_NAME, "SUCCESS - DUMMY")
        slot = DeviceSlot(_build_dummy(config))
        slot.monitor = DeviceMonitor(
            name=DEVICE_NAME,
            slot=slot,
            build_real=lambda: _build_real(config),
            build_dummy=lambda: _build_dummy(config),
            poll_interval=poll_interval,
            desired_powered=False,
        )
        slot.monitor_task = start_device_monitor(slot.monitor)
        return slot

    try:
        instance: CameraInterface = _build_real(config)
        log_device_status(DEVICE_NAME, "SUCCESS")
    except Exception as e:
        log_device_status(DEVICE_NAME, "ERROR")
        print(f"Failed to initialize {DEVICE_NAME}: {e}")
        log_device_status(DEVICE_NAME, "ERROR - FALLBACK TO DUMMY")
        instance = _build_dummy(config)

    slot = DeviceSlot(instance)

    # Referencja do taska trzymana na obiekcie slotu, zeby monitor nie zostal
    # zebrany przez GC dopoki slot (uzywany przez RobotController) zyje -
    # asyncio nie trzyma silnej referencji do tasku samodzielnie.
    monitor = DeviceMonitor(
        name=DEVICE_NAME,
        slot=slot,
        build_real=lambda: _build_real(config),
        build_dummy=lambda: _build_dummy(config),
        poll_interval=poll_interval,
    )
    slot.monitor = monitor
    slot.monitor_task = start_device_monitor(monitor)

    return slot
