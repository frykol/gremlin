import time
import gpiod
from gpiod.line import Direction, Bias

PINS = [17, 27, 23, 24, 25, 5, 6, 16]


def main():
    config = {p: gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_UP) for p in PINS}

    with gpiod.request_lines("/dev/gpiochip0", consumer="debug", config=config) as req:
        last = {p: None for p in PINS}
        print("Obracaj kolem recznie... Ctrl+C aby zakonczyc")
        while True:
            values = req.get_values(PINS)
            for p, v in zip(PINS, values):
                if v != last[p]:
                    print(f"GPIO{p}: {v}")
                    last[p] = v
            time.sleep(0.02)


if __name__ == "__main__":
    main()
