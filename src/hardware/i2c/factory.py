from .interface import I2CPWMInterface
from .dummy_i2c_pwm import DummyI2CPWM
from ..status_log import log_device_status

DEVICE_NAME = "I2C"


def create_i2c_pwm(config: dict) -> I2CPWMInterface:
    i2c_config = config.get("i2c_pwm", {})

    is_dummy = i2c_config.get("is_dummy", False)

    if is_dummy:
        log_device_status(DEVICE_NAME, "SUCCESS - DUMMY")
        return DummyI2CPWM()

    from .i2c_pwm import i2cPWM

    try:
        pwm = i2cPWM()
        # Magistrala I2C otwiera sie dopiero w start(), nie w __init__ -
        # bez tego wywolania brak/awaria sterownika PWM nigdy nie trafialaby do try.
        pwm.start()
    except Exception as e:
        log_device_status(DEVICE_NAME, "ERROR")
        print(f"Failed to initialize {DEVICE_NAME}: {e}")
        log_device_status(DEVICE_NAME, "ERROR - FALLBACK TO DUMMY")
        return DummyI2CPWM()

    log_device_status(DEVICE_NAME, "SUCCESS")
    return pwm
