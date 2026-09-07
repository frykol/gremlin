from typing import Dict, Tuple

# Wheel roles and per-role sign for turning in place / driving forward,
# mirroring DIRECTIONS in site/public/tabs/control.js so backend and manual
# frontend driving agree on which way is "left"/"forward".
FORWARD_SIGN = {"FL": -1, "FR": -1, "RL": -1, "RR": -1}
TURN_RIGHT_SIGN = {"FL": 1, "FR": -1, "RL": 1, "RR": -1}

WHEEL_ROLES = ("FL", "FR", "RL", "RR")

# How much the horizontal offset (-1..1) contributes to turning vs how much
# it suppresses forward speed - a large offset should mostly turn in place,
# a small one should mostly drive forward.
MAX_TURN_RATIO = 1.0


def compute_follow_vector(target_bbox: Tuple[int, int, int, int], frame_width: int) -> Tuple[float, float]:
    """Zwraca (vy, omega) w zakresie [-1, 1] na podstawie polozenia target_bbox
    wzgledem srodka obrazu: vy = jazda do przodu, omega = skret (dodatni = w prawo)."""
    if frame_width <= 0:
        return 0.0, 0.0

    x, _y, w, _h = target_bbox
    bbox_center_x = x + w / 2
    frame_center_x = frame_width / 2

    offset_ratio = (bbox_center_x - frame_center_x) / frame_center_x
    offset_ratio = max(-1.0, min(1.0, offset_ratio))

    omega = offset_ratio * MAX_TURN_RATIO
    vy = 1.0 - abs(offset_ratio)

    return vy, omega


def compute_follow_pwm(
    target_bbox: Tuple[int, int, int, int],
    frame_width: int,
    max_pwm: int,
    motor_pairs: Dict[str, Tuple[int, int]],
) -> Dict[int, int]:
    """Liczy PWM per kanal silnika, zeby jechac w strone target_bbox. Zwraca mape
    {kanal: pwm} obejmujaca wszystkie kanaly z motor_pairs (0 gdy nieaktywny)."""
    vy, omega = compute_follow_vector(target_bbox, frame_width)

    channel_values: Dict[int, int] = {}
    for role in WHEEL_ROLES:
        pair = motor_pairs.get(role)
        if not pair:
            continue
        forward_channel, backward_channel = pair

        net = (vy * FORWARD_SIGN[role] + omega * TURN_RIGHT_SIGN[role]) * max_pwm

        if net > 0:
            channel_values[forward_channel] = round(min(net, max_pwm))
            channel_values[backward_channel] = 0
        elif net < 0:
            channel_values[forward_channel] = 0
            channel_values[backward_channel] = round(min(-net, max_pwm))
        else:
            channel_values[forward_channel] = 0
            channel_values[backward_channel] = 0

    return channel_values


def stop_pwm(motor_pairs: Dict[str, Tuple[int, int]]) -> Dict[int, int]:
    channel_values: Dict[int, int] = {}
    for pair in motor_pairs.values():
        for channel in pair:
            channel_values[channel] = 0
    return channel_values
