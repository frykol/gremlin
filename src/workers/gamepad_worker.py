import asyncio
import json

from src.hardware.device_slot import resolve
from src.hardware.gamepad.interface import GamepadState
from src.logic.follow_band import compute_drive_pwm
from src.robot_state import RobotState


class GamepadWorker:
    def __init__(
        self,
        gamepad,
        state: RobotState,
        gamepad_ws,
        i2c_pwm=None,
        motor_pairs: dict | None = None,
        drive_max_pwm: int = 1500,
        drive_max_pwm_cap: int = 2000,
        drive_max_pwm_step: int = 100,
        drive_boost_pwm: int = 150,
        drive_forward_axis: str = "left_stick_y",
        drive_lateral_axis: str = "left_stick_x",
        drive_turn_axis: str = "right_stick_x",
        drive_speed_down_button: str = "bumper_l",
        drive_speed_up_button: str = "bumper_r",
        drive_boost_button: str = "trigger_l",
        poll_interval: float = 0.005,
        action_handler=None,
    ):
        self.gamepad = gamepad
        self.state: RobotState = state
        self.gamepad_ws = gamepad_ws
        self.i2c_pwm = i2c_pwm
        self.motor_pairs = motor_pairs
        self.drive_max_pwm_cap = drive_max_pwm_cap
        self.drive_max_pwm_step = drive_max_pwm_step
        self.drive_boost_pwm = drive_boost_pwm
        self.drive_forward_axis = drive_forward_axis
        self.drive_lateral_axis = drive_lateral_axis
        self.drive_turn_axis = drive_turn_axis
        self.drive_speed_down_button = drive_speed_down_button
        self.drive_speed_up_button = drive_speed_up_button
        self.drive_boost_button = drive_boost_button
        self.poll_interval: float = poll_interval
        self.action_handler = action_handler

        # Aktualny limit PWM, regulowany w locie przyciskami LB/RB (+-
        # drive_max_pwm_step, w widelkach [0, drive_max_pwm_cap]) - startuje
        # od wartosci z configu.
        self.current_max_pwm: int = max(0, min(drive_max_pwm, drive_max_pwm_cap))
        self._prev_buttons: dict[str, bool] = {}
        self._triggered_action_buttons: set[str] = set()

        self.running: bool = False
        self.task: asyncio.Task | None = None
        self._last_sent: GamepadState | None = None

    def _update_speed_limit(self, buttons: dict) -> None:
        speed_down = buttons.get(self.drive_speed_down_button, False)
        if speed_down and not self._prev_buttons.get(self.drive_speed_down_button, False):
            self.current_max_pwm = max(0, self.current_max_pwm - self.drive_max_pwm_step)

        speed_up = buttons.get(self.drive_speed_up_button, False)
        if speed_up and not self._prev_buttons.get(self.drive_speed_up_button, False):
            self.current_max_pwm = min(self.drive_max_pwm_cap, self.current_max_pwm + self.drive_max_pwm_step)

        self._prev_buttons = dict(buttons)

    async def _handle_bound_actions(self, current: GamepadState) -> None:
        actions = getattr(self.state, "gamepad_actions", {}) or {}
        if not actions:
            return

        for button_name, action in actions.items():
            pressed = bool(current.buttons.get(button_name, False))
            if pressed and button_name not in self._triggered_action_buttons:
                self._triggered_action_buttons.add(button_name)
                if self.action_handler is not None:
                    result = self.action_handler(dict(action))
                    if asyncio.iscoroutine(result):
                        await result
            elif not pressed:
                self._triggered_action_buttons.discard(button_name)

    def _drive(self, current: GamepadState) -> None:
        if self.i2c_pwm is None or self.motor_pairs is None:
            return

        self._update_speed_limit(current.buttons)

        if self.state.follow_band_mode:
            # tryb podazania steruje silnikami sam - ignorujemy gamepada,
            # zeby nie kolidowac z autonomiczna jazda (ten sam wzorzec co
            # reczne komendy "motor" z site w command_processor.py)
            return

        # Push stick w gore zmniejsza surowa wartosc osi Y w strone min ->
        # normalize_axis_value zwraca -1 - odwracamy znak, zeby "do przodu"
        # (push w gore) odpowiadalo dodatniemu vy, tak jak w follow_band.py.
        vy = -current.axes.get(self.drive_forward_axis, 0.0)
        lateral = current.axes.get(self.drive_lateral_axis, 0.0)
        omega = current.axes.get(self.drive_turn_axis, 0.0)

        max_pwm = self.current_max_pwm
        if current.buttons.get(self.drive_boost_button, False):
            # Chwilowy boost trzymany tylko podczas wcisniecia - nie zmienia
            # current_max_pwm na stale, tylko podbija limit na ten jeden tick.
            max_pwm = min(self.drive_max_pwm_cap, max_pwm + self.drive_boost_pwm)

        channel_values = compute_drive_pwm(
            vy,
            omega,
            max_pwm,
            self.motor_pairs,
            lateral=lateral,
        )
        i2c_pwm = resolve(self.i2c_pwm)
        for channel, pwm in channel_values.items():
            i2c_pwm.set_pwm(channel, 0, pwm)

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

                # Sterowanie i wyslanie stanu przez websocket sa wyzwalane
                # tym samym warunkiem "cos sie zmienilo" - dzieki temu obie
                # reakcje sa tak szybkie, jak tylko poll_interval pozwala
                # (domyslnie 5ms), zamiast czekac na osobny, wolniejszy tick.
                if current != self._last_sent:
                    self._last_sent = GamepadState(buttons=dict(current.buttons), axes=dict(current.axes))

                    await self._handle_bound_actions(current)
                    self._drive(current)

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
