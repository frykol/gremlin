from src.workers.ads1115_worker import ADS1115Worker
from src.robot_state import RobotState


class FakeAds1115:
    IS_DUMMY = False


def test_low_voltage_shutdown_can_be_disabled():
    worker = ADS1115Worker(
        ads1115=FakeAds1115(),
        state=RobotState(),
        shutdown_min_voltage=12,
        low_voltage_shutdown_enabled=False,
    )

    worker._check_low_voltage_shutdown(1)

    assert worker._shutdown_triggered is False


def test_low_voltage_shutdown_remains_enabled_by_default():
    worker = ADS1115Worker(
        ads1115=FakeAds1115(),
        state=RobotState(),
        shutdown_min_voltage=None,
    )

    assert worker.low_voltage_shutdown_enabled is True
