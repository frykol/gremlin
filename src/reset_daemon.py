import time
import shutil
from pathlib import Path

import gpiod
from gpiod.line import Direction, Bias, Value

from .config import load_config
from .hardware.sd_card.factory import create_sd_card

POLL_INTERVAL = 0.05

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "custom_basic_structure"


def _copy_template_to_sd_card(mount_point: str) -> None:
    print(f"Przywracam domyślny szkielet na kartę SD: {mount_point}")
    shutil.copytree(_TEMPLATE_DIR, mount_point, dirs_exist_ok=True)
    print("Gotowe.")


def main():
    config = load_config("config.json")

    button_config = config.get("reset_button", {})
    chip = config["gpio"]["chip"]
    pin = button_config.get("pin", 21)
    hold_seconds = button_config.get("hold_seconds", 5)

    request = gpiod.request_lines(
        chip,
        consumer="reset-button",
        config={
            pin: gpiod.LineSettings(
                direction=Direction.INPUT,
                bias=Bias.PULL_UP,
                active_low=True,
            )
        },
    )

    sd_card = create_sd_card(config)

    pressed_since: float | None = None
    triggered = False

    print(f"Nasłuchuję przycisku reset na GPIO{pin} (przytrzymaj {hold_seconds}s)")

    try:
        while True:
            pressed = request.get_value(pin) == Value.ACTIVE

            if pressed:
                if pressed_since is None:
                    pressed_since = time.monotonic()

                if not triggered and (time.monotonic() - pressed_since) >= hold_seconds:
                    triggered = True
                    sd_card.start()
                    _copy_template_to_sd_card(sd_card.mount_point)
            else:
                pressed_since = None
                triggered = False

            time.sleep(POLL_INTERVAL)
    finally:
        request.release()


if __name__ == "__main__":
    main()
