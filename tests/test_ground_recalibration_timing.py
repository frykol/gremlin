from backend.lidar.app import (
    GROUND_RECALIBRATION_INTERVAL_S,
    GROUND_RECALIBRATION_RETRY_INTERVAL_S,
    should_recalibrate_ground,
)


def test_true_when_never_attempted():
    # Pierwszy tick (last_attempt_time = -inf) - probuj natychmiast.
    assert should_recalibrate_ground(
        is_calibrated=False,
        now=100.0,
        last_attempt_time=float("-inf"),
        interval_s=30.0,
        retry_interval_s=2.0,
    )


def test_false_immediately_after_calibration():
    now = 100.0
    assert not should_recalibrate_ground(
        is_calibrated=True, now=now, last_attempt_time=now, interval_s=30.0, retry_interval_s=2.0
    )


def test_false_just_before_interval_elapses():
    now = 100.0
    last = now - (GROUND_RECALIBRATION_INTERVAL_S - 0.01)
    assert not should_recalibrate_ground(
        is_calibrated=True,
        now=now,
        last_attempt_time=last,
        interval_s=GROUND_RECALIBRATION_INTERVAL_S,
        retry_interval_s=GROUND_RECALIBRATION_RETRY_INTERVAL_S,
    )


def test_true_exactly_at_interval():
    now = 100.0
    last = now - GROUND_RECALIBRATION_INTERVAL_S
    assert should_recalibrate_ground(
        is_calibrated=True,
        now=now,
        last_attempt_time=last,
        interval_s=GROUND_RECALIBRATION_INTERVAL_S,
        retry_interval_s=GROUND_RECALIBRATION_RETRY_INTERVAL_S,
    )


def test_true_well_after_interval_elapsed():
    now = 100.0
    last = now - GROUND_RECALIBRATION_INTERVAL_S - 60.0
    assert should_recalibrate_ground(
        is_calibrated=True,
        now=now,
        last_attempt_time=last,
        interval_s=GROUND_RECALIBRATION_INTERVAL_S,
        retry_interval_s=GROUND_RECALIBRATION_RETRY_INTERVAL_S,
    )


def test_uncalibrated_backs_off_between_retries():
    # Nieudana kalibracja (np. robot przodem do sciany - fit_ground_plane
    # odrzuca niepoziome plaszczyzny) NIE moze ponawiac RANSAC co tick:
    # zmierzone 41ms na 30k punktach to ~20% budzetu obstacle_loop (200ms)
    # zajmowane w kolko. Miedzy probami obowiazuje krotki backoff.
    now = 100.0
    last = now - (GROUND_RECALIBRATION_RETRY_INTERVAL_S - 0.01)
    assert not should_recalibrate_ground(
        is_calibrated=False,
        now=now,
        last_attempt_time=last,
        interval_s=GROUND_RECALIBRATION_INTERVAL_S,
        retry_interval_s=GROUND_RECALIBRATION_RETRY_INTERVAL_S,
    )


def test_uncalibrated_retries_after_short_backoff():
    # ...ale backoff jest KROTKI (nie pelne 30s), zeby robot skalibrowal sie
    # szybko, gdy tylko podloga wroci w pole widzenia.
    now = 100.0
    last = now - GROUND_RECALIBRATION_RETRY_INTERVAL_S
    assert should_recalibrate_ground(
        is_calibrated=False,
        now=now,
        last_attempt_time=last,
        interval_s=GROUND_RECALIBRATION_INTERVAL_S,
        retry_interval_s=GROUND_RECALIBRATION_RETRY_INTERVAL_S,
    )


def test_retry_interval_is_much_shorter_than_refresh_interval():
    assert GROUND_RECALIBRATION_RETRY_INTERVAL_S < GROUND_RECALIBRATION_INTERVAL_S
