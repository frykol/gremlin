import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from motor_driver.odometry import wrap_to_pi, integrate_odometry, quaternion_from_yaw


def test_wrap_to_pi_identity_within_range():
    assert wrap_to_pi(0.5) == pytest_approx(0.5)


def test_wrap_to_pi_wraps_positive_overflow():
    result = wrap_to_pi(math.pi + 0.1)
    assert result == pytest_approx(-math.pi + 0.1)


def test_wrap_to_pi_wraps_negative_overflow():
    result = wrap_to_pi(-math.pi - 0.1)
    assert result == pytest_approx(math.pi - 0.1)


def test_integrate_odometry_pure_forward_motion():
    x, y, theta = integrate_odometry(
        x=0.0, y=0.0, theta=0.0, vx=1.0, vy=0.0, wz=0.0, dt=1.0
    )
    assert x == pytest_approx(1.0)
    assert y == pytest_approx(0.0)
    assert theta == pytest_approx(0.0)


def test_integrate_odometry_pure_rotation():
    x, y, theta = integrate_odometry(
        x=0.0, y=0.0, theta=0.0, vx=0.0, vy=0.0, wz=math.pi / 2, dt=1.0
    )
    assert x == pytest_approx(0.0)
    assert y == pytest_approx(0.0)
    assert theta == pytest_approx(math.pi / 2)


def test_integrate_odometry_forward_motion_rotates_with_existing_heading():
    # Robot already facing +90deg (theta=pi/2): commanding vx should move
    # it in +y in the odom frame, not +x.
    x, y, theta = integrate_odometry(
        x=0.0, y=0.0, theta=math.pi / 2, vx=1.0, vy=0.0, wz=0.0, dt=1.0
    )
    assert x == pytest_approx(0.0, abs=1e-9)
    assert y == pytest_approx(1.0)
    assert theta == pytest_approx(math.pi / 2)


def test_integrate_odometry_zero_dt_is_noop():
    x, y, theta = integrate_odometry(
        x=1.0, y=2.0, theta=0.3, vx=5.0, vy=5.0, wz=5.0, dt=0.0
    )
    assert x == pytest_approx(1.0)
    assert y == pytest_approx(2.0)
    assert theta == pytest_approx(0.3)


def test_quaternion_from_yaw_zero():
    qz, qw = quaternion_from_yaw(0.0)
    assert qz == pytest_approx(0.0)
    assert qw == pytest_approx(1.0)


def test_quaternion_from_yaw_half_pi():
    qz, qw = quaternion_from_yaw(math.pi / 2)
    assert qz == pytest_approx(math.sin(math.pi / 4))
    assert qw == pytest_approx(math.cos(math.pi / 4))


def pytest_approx(value, abs=1e-9):
    import pytest
    return pytest.approx(value, abs=abs)
