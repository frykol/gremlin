class i2cPWMDummy:
    def __init__(self):
        self.started: bool = False

    def start(self) -> None:
        self.started = True
        print("I2C PWM (symulacja) gotowe")

    def set_pwm(self, ch, on, off) -> None:
        pass

    def set_pwm_percent(self, ch: int, percent: float):
        pass
