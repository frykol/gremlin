from .interface import I2CPWMInterface
from .dummy_i2c_pwm import DummyI2CPWM


def create_i2c_pwm(config: dict) -> I2CPWMInterface:
    i2c_config = config.get("i2c_pwm", {})

    is_dummy = i2c_config.get("is_dummy", False)

    if is_dummy:
        return DummyI2CPWM()

    from .i2c_pwm import i2cPWM

    return i2cPWM()
