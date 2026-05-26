import gpiod
from gpiod import LineRequest
from gpiod.line import Direction, Value
from src.config import load_config

class GPIOController:
    def __init__(self):
        self.gpio_config: dict = load_config("config.json")["gpio"]

        self.chip: str = self.gpio_config["chip"]
        self.pins: dict = self.gpio_config["pins"]
        self.standard_pins: dict = self.gpio_config["standard_pins"]

        self.prepared: bool = False
        self.request: gpiod.LineRequest | None = None

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

    def set_named_pin(self, pin_name: str, pin_state: bool) -> None:
        if not self.request:
            return
        if pin_name not in self.pins:
            raise KeyError(f"Nieznany nazwany pin: {pin_name}")

        value = Value.ACTIVE if pin_state else Value.INACTIVE

        self.request.set_value(self.pins[pin_name], value)
    
    def set_standard_pin(self, pin_name: str, pin_state: bool) -> None:
        if not self.request:
            return
        if pin_name not in self.standard_pins:
            raise KeyError(f"Nieznany standardowy pin: {pin_name}")

        value = Value.ACTIVE if pin_state else Value.INACTIVE

        self.request.set_value(self.standard_pins[pin_name], value)

    
        
