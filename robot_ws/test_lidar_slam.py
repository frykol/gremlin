import numpy as np

from lidar_slam import LidarSlam


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
