from abc import ABC, abstractmethod

class I2CPWMInterface(ABC):
    @abstractmethod
    def start(self) -> None:
        pass

    @abstractmethod
    def set_pwm(self, ch: int, on: int, off: int) -> None:
        pass

    @abstractmethod
    def set_pwm_percent(self, ch: int, percent: float) -> None:
        pass
