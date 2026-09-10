"""DeviceMonitor buduje dummy w trakcie dzialania robota, po tym jak worker
(CameraWorker/LidarWorker/ADS1115Worker/MicWorker) juz dawno wywolal .start()
raz, przy starcie calego robota. Jesli _build_dummy nie wystartuje swiezej
instancji sam, dane przestaja plynac na dobre po pierwszym fallbacku - patrz
test_camera_factory.py dla oryginalnego przypadku (OAK-D)."""

from src.hardware.lidar.factory import _build_dummy as build_dummy_lidar
from src.hardware.ads1115.factory import _build_dummy as build_dummy_ads1115
from src.hardware.i2c.factory import _build_dummy as build_dummy_i2c
from src.hardware.respeaker.factory import _build_dummy as build_dummy_mic
from src.hardware.sd_card.factory import _build_dummy as build_dummy_sd_card
from src.hardware.gamepad.factory import _build_dummy as build_dummy_gamepad


def test_build_dummy_lidar_is_already_started():
    lidar = build_dummy_lidar({})
    assert lidar.running is True
    assert lidar.read_points() != []


def test_build_dummy_ads1115_is_already_started():
    ads = build_dummy_ads1115({})
    assert ads.running is True
    assert len(ads.read_channels()) == 4


def test_build_dummy_i2c_is_already_started():
    pwm = build_dummy_i2c({})
    assert pwm.started is True


def test_build_dummy_mic_is_already_started():
    mic = build_dummy_mic({})
    assert mic.running is True
    assert mic.get_audio_chunk() is not None


def test_build_dummy_sd_card_is_already_started():
    sd_card = build_dummy_sd_card({})
    assert sd_card.running is True
    assert sd_card.write_file("probe.txt", b"x") is True


def test_build_dummy_gamepad_is_already_started():
    gamepad = build_dummy_gamepad({"gamepad": {"mapping": {"BTN_SOUTH": "a"}}})
    assert gamepad.running is True
    assert gamepad.get_state().buttons == {"a": False}
