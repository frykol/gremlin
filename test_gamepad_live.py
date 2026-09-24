import asyncio, json
from src.hardware.gamepad.gamepad import Gamepad
from src.logic.follow_band import compute_drive_pwm

MOTOR_PAIRS = {"FL": (0, 1), "FR": (3, 2), "RL": (4, 5), "RR": (7, 6)}


async def main():
    gamepad_config = json.load(open("config.json"))["gamepad"]
    mapping = gamepad_config["mapping"]
    max_pwm = gamepad_config.get("drive_max_pwm", 1500)

    loop = asyncio.get_running_loop()
    gp = Gamepad(mapping=mapping, loop=loop)
    gp.start()
    print("Wcisnij przyciski / rusz galkami - Ctrl+C zeby zakonczyc")
    print("(to tylko podglad - NIE steruje realnymi silnikami)")
    last = None
    try:
        while True:
            await asyncio.sleep(0.05)
            s = gp.get_state()
            cur = (tuple(sorted(s.buttons.items())), tuple(sorted(s.axes.items())))
            if cur != last:
                vy = -s.axes.get(gamepad_config.get("drive_forward_axis", "right_stick_y"), 0.0)
                omega = s.axes.get(gamepad_config.get("drive_turn_axis", "left_stick_x"), 0.0)
                pwm = compute_drive_pwm(vy, omega, max_pwm, MOTOR_PAIRS)
                print("buttons:", s.buttons)
                print("axes:", s.axes)
                print(f"  -> vy={vy:.2f} omega={omega:.2f} pwm={pwm}")
                last = cur
    except KeyboardInterrupt:
        pass
    finally:
        gp.stop()


asyncio.run(main())
