import pytest

from wheel_kinematics import pwm_pair_to_signed_fraction, wheel_speeds_to_body_velocity


def test_pwm_pair_full_forward():
    assert pwm_pair_to_signed_fraction(4095, 0, pwm_max=4095) == pytest.approx(1.0)


def test_pwm_pair_full_backward():
    assert pwm_pair_to_signed_fraction(0, 4095, pwm_max=4095) == pytest.approx(-1.0)


def test_pwm_pair_stopped():
    assert pwm_pair_to_signed_fraction(0, 0, pwm_max=4095) == pytest.approx(0.0)


def test_pwm_pair_half_forward():
    assert pwm_pair_to_signed_fraction(2048, 0, pwm_max=4095) == pytest.approx(2048 / 4095)


def test_wheel_speeds_pure_forward():
    # r=1, half_wheelbase=1, half_track=1: wszystkie kola ta sama predkosc
    vx, vy, wz = wheel_speeds_to_body_velocity(
        w_fl=2.0, w_fr=2.0, w_rl=2.0, w_rr=2.0,
        wheel_radius_m=1.0, half_wheelbase_m=1.0, half_track_m=1.0,
    )
    assert vx == pytest.approx(2.0)
    assert vy == pytest.approx(0.0)
    assert wz == pytest.approx(0.0)


def test_wheel_speeds_pure_rotation():
    vx, vy, wz = wheel_speeds_to_body_velocity(
        w_fl=-2.0, w_fr=2.0, w_rl=-2.0, w_rr=2.0,
        wheel_radius_m=1.0, half_wheelbase_m=1.0, half_track_m=1.0,
    )
    assert vx == pytest.approx(0.0)
    assert vy == pytest.approx(0.0)
    assert wz == pytest.approx(1.0)


def test_wheel_speeds_pure_strafe():
    vx, vy, wz = wheel_speeds_to_body_velocity(
        w_fl=-2.0, w_fr=2.0, w_rl=2.0, w_rr=-2.0,
        wheel_radius_m=1.0, half_wheelbase_m=1.0, half_track_m=1.0,
    )
    assert vx == pytest.approx(0.0)
    assert vy == pytest.approx(2.0)
    assert wz == pytest.approx(0.0)


def test_wheel_speeds_uses_physical_defaults():
    # Sanity check ze domyslne stale to fizyczna geometria robota, nie
    # wartosci testowe r=1 z powyzszych testow.
    vx, vy, wz = wheel_speeds_to_body_velocity(w_fl=10.0, w_fr=10.0, w_rl=10.0, w_rr=10.0)
    assert vx == pytest.approx(0.024 * 10.0)


def test_wheel_speeds_rejects_zero_wheel_radius():
    with pytest.raises(ValueError, match="wheel_radius_m"):
        wheel_speeds_to_body_velocity(
            w_fl=1.0, w_fr=1.0, w_rl=1.0, w_rr=1.0,
            wheel_radius_m=0.0, half_wheelbase_m=1.0, half_track_m=1.0,
        )


def test_wheel_speeds_rejects_zero_geometry_sum():
    with pytest.raises(ValueError, match="half_wheelbase_m \\+ half_track_m"):
        wheel_speeds_to_body_velocity(
            w_fl=1.0, w_fr=1.0, w_rl=1.0, w_rr=1.0,
            wheel_radius_m=1.0, half_wheelbase_m=0.0, half_track_m=0.0,
        )
