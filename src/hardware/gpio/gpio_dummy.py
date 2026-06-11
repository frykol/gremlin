from src.config import load_config


class GPIOControllerDummy:
    def __init__(self):
        gpio_config = load_config("config.json")["gpio"]
        self.pins: dict = gpio_config["pins"]
        self.standard_pins: dict = gpio_config["standard_pins"]
        self.prepared: bool = False

    def setup(self, active: bool = True) -> None:
        self.prepared = True
        print("GPIO (symulacja) gotowe")

    def set_named_pin(self, pin_name: str, pin_state: bool) -> None:
        print(f"GPIO {pin_name} -> {pin_state}")

    def set_standard_pin(self, pin_name: str, pin_state: bool) -> None:
        print(f"GPIO {pin_name} -> {pin_state}")
