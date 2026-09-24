from src.hardware.oak_d.factory import _build_dummy


def test_build_dummy_camera_is_already_started():
    """DeviceMonitor buduje dummy w trakcie dzialania robota, po tym jak
    CameraWorker.start() jest juz dawno wywolane (wola sie tylko raz, przy
    starcie calego robota) - jesli _build_dummy nie wystartuje kamery sam,
    get_camera_frame() zwraca None w nieskonczonosc i podglad zamraza sie na
    ostatniej klatce sprzed awarii zamiast pokazywac placeholder dummy."""
    camera = _build_dummy({"oak_d": {"width": 64, "height": 48}})

    assert camera.running is True
    assert camera.get_camera_frame() is not None
