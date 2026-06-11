class GestureExecutor:
    """Wykonuje komendy z gestow. Na razie domyslnie tylko podglad."""

    def __init__(self, execute_commands: bool = False):
        self.execute_commands = execute_commands

    def handle(self, finger_count: int, gesture_name: str) -> None:
        if not self.execute_commands:
            return

        # TODO: podlaczyc GPIO, silniki lub WebSocket gdy execute_commands=True
