import gpiod
from gpiod.line import Direction, Value
from src.config import load_config

class GPIOController:
    def __init__(self):
        self.gpio_config = load_config("config.json")["gpio"]

        self.chip = self.gpio_config["chip"]
        self.pins = self.gpio_config["pins"]

        self.prepared = False
        self.request = None

    def setup(self, active: bool = True) -> None:
        config = {}

        for pin_name, pin_number in self.pins.items():
            config[pin_number] = gpiod.LineSettings(
            direction=Direction.OUTPUT,
            output_value=Value.INACTIVE,
        )

        self.request = gpiod.request_lines(
                self.chip,
                consumer="ib2-en",
                config=config,
        )
        self.prepared = True

    def set_pin(self, pin_name: str, pin_state: bool) -> None:
        if pin_name not in self.pins:
            raise KeyError(f"Nieznany pin: {pin_name}")

        value = Value.ACTIVE if pin_state else Value.INACTIVE

        self.request.set_value(self.pins[pin_name], value)
        
