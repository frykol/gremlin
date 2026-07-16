from .interface import I2CPWMInterface


class DummyI2CPWM(I2CPWMInterface):
    def __init__(self, **kwargs):
        self.started: bool = False

    def start(self) -> None:
        self.started = True
        print("i2cPWM (dummy) działa")

    def set_pwm(self, ch: int, on: int, off: int) -> None:
        if not self.started:
            return
        print(f"i2cPWM (dummy) set_pwm ch={ch} on={on} off={off}")

    def set_pwm_percent(self, ch: int, percent: float) -> None:
        if not self.started:
            return
        percent = max(0, min(100, percent))
        print(f"i2cPWM (dummy) set_pwm_percent ch={ch} percent={percent}")
