import asyncio

from .interface import I2CPWMInterface
from .dummy_i2c_pwm import DummyI2CPWM
from ..status_log import log_device_status
from ..device_slot import DeviceSlot
from ..device_monitor import DeviceMonitor, start_device_monitor

DEVICE_NAME = "I2C"


def _build_dummy(config: dict) -> I2CPWMInterface:
    # DeviceMonitor podmienia instancje w slocie w trakcie dzialania robota -
    # zaden worker nie wywola juz .start() na tej nowej instancji (robi to
    # tylko raz, przy starcie calego robota), wiec musimy ja wystartowac
    # tutaj, inaczej dane przestalyby plynac na dobre po pierwszym fallbacku.
    pwm = DummyI2CPWM()
    pwm.start()
    return pwm


def _build_real(config: dict) -> I2CPWMInterface:
    from .i2c_pwm import i2cPWM

    # Magistrala I2C otwiera sie dopiero w start(), nie w __init__ - bez tego
    # wywolania brak/awaria sterownika PWM nigdy nie trafialaby do try.
    pwm = i2cPWM()
    pwm.start()
    return pwm


def create_i2c_pwm(config: dict) -> DeviceSlot:
    i2c_config = config.get("i2c_pwm", {})
    is_dummy = i2c_config.get("is_dummy", False)
    poll_interval = config.get("device_health_check_interval", 5.0)

    if is_dummy:
        log_device_status(DEVICE_NAME, "SUCCESS - DUMMY")
        return DeviceSlot(_build_dummy(config))

    try:
        instance: I2CPWMInterface = _build_real(config)
        log_device_status(DEVICE_NAME, "SUCCESS")
    except Exception as e:
        log_device_status(DEVICE_NAME, "ERROR")
        print(f"Failed to initialize {DEVICE_NAME}: {e}")
        log_device_status(DEVICE_NAME, "ERROR - FALLBACK TO DUMMY")
        instance = _build_dummy(config)

    slot = DeviceSlot(instance)

    monitor = DeviceMonitor(
        name=DEVICE_NAME,
        slot=slot,
        build_real=lambda: _build_real(config),
        build_dummy=lambda: _build_dummy(config),
        poll_interval=poll_interval,
    )
    slot.monitor_task = start_device_monitor(monitor)

    return slot
