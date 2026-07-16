import json

import numpy as np
import pytest

from lidar_slam import LidarSlam, WheelCalibrationError, load_wheel_calibration


def make_corner_cloud(n_per_face=200, seed=0):
    """Chmura punktow w ksztalcie naroznika (dwie prostopadle plaszczyzny)
    - w przeciwienstwie do pojedynczej plaskiej sciany daje ICP
    wystarczajaco cech geometrycznych do jednoznacznego dopasowania w obu
    osiach X i Y."""
    rng = np.random.default_rng(seed)
    face1 = np.column_stack([
        rng.uniform(-2, 2, n_per_face),
        np.zeros(n_per_face),
        rng.uniform(0, 2, n_per_face),
    ])
    face2 = np.column_stack([
        np.zeros(n_per_face),
        rng.uniform(-2, 2, n_per_face),
        rng.uniform(0, 2, n_per_face),
    ])
    return np.vstack([face1, face2])


def test_add_frame_converges_with_accurate_odom_guess():
    points = make_corner_cloud()
    intensity = np.full(len(points), 150.0)

    slam = LidarSlam(min_fitness=0.3, max_speed=100.0)
    status0 = slam.add_frame(points, intensity, t_stamp=0.0)
    assert status0 == "ok"

    true_translation = np.array([0.3, -0.15, 0.0])
    moved_points = points - true_translation  # w ukladzie czujnika po ruchu

    dR_odom = np.eye(3)
    dt_odom = true_translation.copy()
    status1 = slam.add_frame(
        moved_points, intensity, t_stamp=0.2, odom_delta=(dR_odom, dt_odom)
    )

    assert status1 == "ok"
    np.testing.assert_allclose(slam.pose_t, true_translation, atol=0.05)


def test_add_frame_rejects_when_odom_prediction_is_way_off():
    points = make_corner_cloud()
    intensity = np.full(len(points), 150.0)

    slam = LidarSlam(min_fitness=0.3, max_speed=100.0)
    slam.add_frame(points, intensity, t_stamp=0.0)

    true_translation = np.array([0.05, 0.0, 0.0])
    moved_points = points - true_translation

    # Odometria twierdzi ze robot pojechal 5m, mimo ze naprawde przesunal
    # sie o 5cm - powinno zostac odrzucone (fitness lub divergencja).
    dR_odom = np.eye(3)
    dt_odom = np.array([5.0, 0.0, 0.0])
    status = slam.add_frame(
        moved_points, intensity, t_stamp=0.2, odom_delta=(dR_odom, dt_odom)
    )

    assert status == "rejected"
    np.testing.assert_allclose(slam.pose_t, np.zeros(3))


def make_periodic_cloud(period=0.15, n_clusters=10, n_per_cluster=80, seed=0):
    """Chmura punktow z powtarzajaca sie struktura wzdluz osi X (rzad
    klastrow co `period`) - klasyczna pulapka lokalnego minimum ICP:
    dopasowanie najblizszego sasiada moze "zablokowac sie" na sasiednim
    powtorzeniu wzorca zamiast prawdziwego odpowiednika, osiagajac wysoki
    fitness (wiekszosc punktow i tak znajduje jakies bliskie dopasowanie,
    tylko o okres dalej) przy pozycji przesunietej od prawdziwej."""
    rng = np.random.default_rng(seed)
    parts = []
    for i in range(n_clusters):
        cx = i * period
        cluster = np.column_stack([
            np.full(n_per_cluster, cx) + rng.uniform(-0.02, 0.02, n_per_cluster),
            rng.uniform(-1, 1, n_per_cluster),
            rng.uniform(0, 1, n_per_cluster),
        ])
        parts.append(cluster)
    return np.vstack(parts)


def test_add_frame_rejects_high_fitness_icp_that_diverges_from_odom():
    """Izoluje bramke divergencji od bramki fitness: dobieramy scene tak,
    zeby ICP osiagnal fitness wyraznie powyzej min_fitness (empirycznie
    fitness=1.00, tj. wszystkie punkty w zasiegu max_corr_dist=0.5
    znajduja dopasowanie), wiec sam check `fitness < self.min_fitness`
    zaakceptowalby ta ramke. Odrzucenie musi wiec pochodzic wylacznie z
    checku divergencji ICP-vs-odometria.

    Mapa ma okresowa strukture (klastry punktow co period=0.15m wzdluz
    X) - klasyczna pulapka lokalnego minimum ICP. Odometria "twierdzi",
    ze robot przejechal dokladnie 2 okresy (0.30m), podczas gdy naprawde
    przesunal sie o 0.03m. Poczatkowe oszacowanie ICP (z odometrii)
    trafia wiec w poblize powtorzenia wzorca, ale przy max_corr_dist=0.5
    korespondencje NN i tak "przyciagaja" ICP z powrotem w okolice
    prawdziwej pozycji (empirycznie: new_pose_t ~= [0.03, 0, 0]) - stad
    divergencja wzgledem przewidywania odometrii (~0.27m) wyraznie
    przekracza tolerancje max_divergence = max(0.1, |dt_odom|*0.5+0.05)
    = 0.20m dla tego dt_odom, mimo perfekcyjnego fitness."""
    points = make_periodic_cloud()
    intensity = np.full(len(points), 150.0)

    slam = LidarSlam(min_fitness=0.3, max_speed=100.0)
    status0 = slam.add_frame(points, intensity, t_stamp=0.0)
    assert status0 == "ok"

    true_translation = np.array([0.03, 0.0, 0.0])
    moved_points = points - true_translation

    # Odometria twierdzi, ze robot przejechal dokladnie 2 okresy wzorca
    # (0.30m), a naprawde przesunal sie o 0.03m - ICP dostaje wiarygodny
    # (nie zbyt daleki) initial guess i osiaga wysoki fitness, ale w
    # zupelnie innym miejscu niz przewidziala odometria.
    dR_odom = np.eye(3)
    dt_odom = np.array([0.3, 0.0, 0.0])
    status = slam.add_frame(
        moved_points, intensity, t_stamp=0.2, odom_delta=(dR_odom, dt_odom)
    )

    assert status == "rejected"
    np.testing.assert_allclose(slam.pose_t, np.zeros(3))


def test_add_frame_without_odom_delta_keeps_zero_motion_fallback():
    points = make_corner_cloud()
    intensity = np.full(len(points), 150.0)

    slam = LidarSlam(min_fitness=0.3, max_speed=100.0)
    slam.add_frame(points, intensity, t_stamp=0.0)

    # Bez odom_delta - dokladnie ta sama chmura (brak ruchu) powinna zostac
    # zaakceptowana z pozycja bliska zeru (dzisiejsze zachowanie).
    status = slam.add_frame(points.copy(), intensity, t_stamp=0.2)

    assert status == "ok"
    np.testing.assert_allclose(slam.pose_t, np.zeros(3), atol=0.05)


def test_load_wheel_calibration_missing_file_raises_clear_error(tmp_path):
    missing_path = tmp_path / "does_not_exist.json"

    with pytest.raises(WheelCalibrationError) as excinfo:
        load_wheel_calibration(str(missing_path))

    assert str(missing_path) in str(excinfo.value)
    assert "calibrate_wheel_speed.py" in str(excinfo.value)


def test_load_wheel_calibration_missing_key_raises_clear_error(tmp_path):
    bad_path = tmp_path / "wheel_calibration.json"
    bad_path.write_text(json.dumps({"not_the_right_key": 1.0}))

    with pytest.raises(WheelCalibrationError) as excinfo:
        load_wheel_calibration(str(bad_path))

    assert str(bad_path) in str(excinfo.value)
