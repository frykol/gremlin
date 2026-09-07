import os
import sys
import asyncio

from .config import load_config
from .hardware.sd_card.factory import create_sd_card
from .hardware.status_log import clear_status_log
from . import default


async def _run(init_fn, loop_fn, config: dict) -> None:
    await init_fn(config)
    await loop_fn(config)


def main():
    config = load_config("config.json")

    clear_status_log()

    sd_card = create_sd_card(config)
    sd_card.start()

    custom_path = os.path.join(sd_card.mount_point, "custom.py")

    if config.get("is_custom", True) and os.path.exists(custom_path):
        sys.path.insert(0, sd_card.mount_point)
        import custom as module
        print(f"Uruchamiam CUSTOM program: {custom_path}")
    else:
        module = default
        print("Uruchamiam DOMYŚLNY program (default.py)")

    asyncio.run(_run(module.init, module.loop, config))


if __name__ == "__main__":
    main()
