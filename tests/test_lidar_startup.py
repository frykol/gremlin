from src.main import _build_lidar_command
from src.hardware.lidar.dummy_lidar import DummyLidar
from src.hardware.lidar.factory import create_lidar


def test_build_lidar_command_uses_configured_bridge_and_serial_port():
    command = _build_lidar_command(
        {
            'lidar': {'port': '/dev/ttyUSB7'},
            'lidar_bridge_path': '/opt/unilidar_publisher_udp',
        }
    )

    assert command[-6:] == [
        '--lidar-bridge-path',
        '/opt/unilidar_publisher_udp',
        '--lidar-serial-port',
        '/dev/ttyUSB7',
        '--port',
        '8767',
    ]


def test_build_lidar_command_finds_sdk_bridge_by_default():
    command = _build_lidar_command({'lidar': {'port': '/dev/ttyUSB0'}})

    assert command[4].endswith('/unilidar_sdk/unitree_lidar_sdk/bin/unilidar_publisher_udp')


def test_external_bridge_uses_dummy_for_legacy_serial_worker():
    lidar = create_lidar({'lidar': {'external_bridge': True}})

    assert isinstance(lidar, DummyLidar)