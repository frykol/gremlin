from .interface import GamepadState

BUTTON_PREFIX = "BTN_"
AXIS_PREFIX = "ABS_"


def is_button_code(code_name: str) -> bool:
    return code_name.startswith(BUTTON_PREFIX)


def is_axis_code(code_name: str) -> bool:
    return code_name.startswith(AXIS_PREFIX)


def neutral_state(mapping: dict[str, str]) -> GamepadState:
    buttons = {name: False for code, name in mapping.items() if is_button_code(code)}
    axes = {name: 0.0 for code, name in mapping.items() if is_axis_code(code)}
    return GamepadState(buttons=buttons, axes=axes)


def normalize_axis_value(raw_value: int, abs_min: int, abs_max: int) -> float:
    """Mapuje surowa wartosc evdev z zakresu [abs_min, abs_max] na [-1.0, 1.0],
    przycinajac wartosci wykraczajace poza zakres raportowany przez urzadzenie."""
    if abs_max == abs_min:
        return 0.0

    span = abs_max - abs_min
    normalized = (2 * (raw_value - abs_min) / span) - 1.0
    return max(-1.0, min(1.0, normalized))
