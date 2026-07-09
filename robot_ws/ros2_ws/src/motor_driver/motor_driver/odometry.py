import math


def wrap_to_pi(angle: float) -> float:
    """Normalize an angle in radians to the range (-pi, pi]."""
    wrapped = math.fmod(angle + math.pi, 2 * math.pi)
    if wrapped <= 0:
        wrapped += 2 * math.pi
    return wrapped - math.pi


def integrate_odometry(x, y, theta, vx, vy, wz, dt):
    """Dead-reckon (x, y, theta) forward by dt using body-frame velocities.

    vx, vy are in the robot's body frame; they are rotated by the current
    heading (theta) before being added to the odom-frame position, matching
    the standard 2D differential-drive/mecanum odometry integration used
    when no wheel encoder feedback is available.
    """
    dx = (vx * math.cos(theta) - vy * math.sin(theta)) * dt
    dy = (vx * math.sin(theta) + vy * math.cos(theta)) * dt
    dtheta = wz * dt

    new_x = x + dx
    new_y = y + dy
    new_theta = wrap_to_pi(theta + dtheta)
    return new_x, new_y, new_theta


def quaternion_from_yaw(theta: float):
    """Return (qz, qw) for a pure yaw rotation, x/y components are 0."""
    return math.sin(theta / 2.0), math.cos(theta / 2.0)
