from .interface import GamepadInterface, GamepadState
from .mapping import neutral_state


class FakeGamepad(GamepadInterface):
    IS_DUMMY = True

    def __init__(self, mapping: dict[str, str] | None = None):
        self.mapping = mapping or {}
        self.running: bool = False

    def start(self) -> None:
        self.running = True
        print("Gamepad (dummy) działa")

    def stop(self) -> None:
        self.running = False
        print("Gamepad (dummy) zatrzymany")

    def get_state(self) -> GamepadState:
        return neutral_state(self.mapping)

    def is_healthy(self) -> bool:
        return True
