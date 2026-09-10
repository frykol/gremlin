import asyncio
import json

from src.hardware.device_slot import resolve
from src.hardware.gamepad.interface import GamepadState
from src.robot_state import RobotState


class GamepadWorker:
    def __init__(self, gamepad, state: RobotState, gamepad_ws, poll_interval: float = 0.005):
        self.gamepad = gamepad
        self.state: RobotState = state
        self.gamepad_ws = gamepad_ws
        self.poll_interval: float = poll_interval

        self.running: bool = False
        self.task: asyncio.Task | None = None
        self._last_sent: GamepadState | None = None

    async def run(self):
        while self.running:
            try:
                current = resolve(self.gamepad).get_state()
            except Exception as exc:
                # Bez tego try/except wyjatek z realnego sprzetu (np. evdev
                # device disappearing on USB unplug) ubijalby cala petle na
                # stale - patrz ten sam problem naprawiony w
                # CameraWorker/LidarWorker/MicWorker.
                print(f"Gamepad read error: {exc}")
                current = None

            if current is not None:
                self.state.gamepad_state = current

                if current != self._last_sent:
                    self._last_sent = GamepadState(buttons=dict(current.buttons), axes=dict(current.axes))
                    try:
                        await self.gamepad_ws.send(json.dumps({
                            "type": "gamepad_state",
                            "buttons": current.buttons,
                            "axes": current.axes,
                        }))
                    except Exception as exc:
                        print(f"Failed to send gamepad state: {exc}")

            await asyncio.sleep(self.poll_interval)

    def start(self):
        if self.running:
            return

        resolve(self.gamepad).start()

        self.running = True
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        self.running = False

        if self.task is not None:
            await self.task

        resolve(self.gamepad).stop()
