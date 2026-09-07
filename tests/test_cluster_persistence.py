from backend.lidar.cluster_persistence import ClusterPersistenceTracker
from backend.lidar.obstacle_clustering import ObstacleCluster


def _cluster(x=0.5, y=0.5, size=0.1, point_count=20):
    return ObstacleCluster(
        x_min=x, x_max=x + size,
        y_min=y, y_max=y + size,
        z_min=0.1, z_max=0.3,
        centroid_x=x + size / 2, centroid_y=y + size / 2, centroid_z=0.2,
        point_count=point_count,
        mean_intensity=150.0,
        intensity_std=10.0,
    )


def test_empty_stays_empty():
    tracker = ClusterPersistenceTracker()
    assert tracker.update([], now=0.0) == []


def test_new_cluster_appears_immediately():
    tracker = ClusterPersistenceTracker()
    c = _cluster()

    result = tracker.update([c], now=0.0)

    assert result == [c]


def test_cluster_persists_through_one_missed_tick():
    tracker = ClusterPersistenceTracker(timeout_s=4.0)
    c = _cluster(x=1.0, y=1.0)
    tracker.update([c], now=0.0)

    # Tick pol sekundy pozniej - klaster NIE wystapil w tym ticku (np.
    # chwilowy szum), ale timeout jeszcze nie uplynal.
    result = tracker.update([], now=0.5)

    assert len(result) == 1
    assert result[0].centroid_x == c.centroid_x


def test_cluster_expires_after_timeout_without_confirmation():
    tracker = ClusterPersistenceTracker(timeout_s=4.0)
    c = _cluster(x=1.0, y=1.0)
    tracker.update([c], now=0.0)

    # 5 sekund bez zadnego potwierdzenia - powinien wygasnac.
    result = tracker.update([], now=5.0)

    assert result == []


def test_matched_cluster_position_updates_and_refreshes_timer():
    tracker = ClusterPersistenceTracker(match_base_m=0.3, match_slope=0.0, timeout_s=4.0)
    c1 = _cluster(x=1.0, y=1.0)
    tracker.update([c1], now=0.0)

    # Nieznaczne przesuniecie (w promieniu match_distance_m) - to wciaz
    # "ten sam" klaster, aktualizuje pozycje i timer.
    c2 = _cluster(x=1.05, y=1.0)
    tracker.update([c2], now=1.0)

    # 3.5s pozniej od OSTATNIEGO potwierdzenia (t=1.0) - wciaz w oknie
    # 4.0s liczonym od c2, mimo ze od c1 minelo juz 4.5s.
    result = tracker.update([], now=4.5)

    assert len(result) == 1
    assert result[0].centroid_x == c2.centroid_x


def test_drastically_different_cluster_is_not_matched_old_expires_independently():
    tracker = ClusterPersistenceTracker(match_base_m=0.3, match_slope=0.0, timeout_s=2.0)
    old = _cluster(x=0.0, y=0.0)
    tracker.update([old], now=0.0)

    # Zupelnie inne miejsce (poza match_distance_m) - traktowane jako NOWY
    # obiekt, nie aktualizacja starego ("diametralna zmiana" = brak
    # dopasowania).
    far = _cluster(x=10.0, y=10.0)
    result = tracker.update([far], now=0.5)

    # Oba widoczne: stary (jeszcze w oknie timeout) + nowy.
    assert len(result) == 2

    # Po uplywie timeout od ostatniego potwierdzenia starego (t=0.0) -
    # zostaje tylko nowy.
    result2 = tracker.update([far], now=2.5)
    assert len(result2) == 1
    assert result2[0].centroid_x == far.centroid_x


def test_multiple_independent_clusters_tracked_separately():
    tracker = ClusterPersistenceTracker(match_base_m=0.3, match_slope=0.0, timeout_s=4.0)
    a = _cluster(x=0.0, y=0.0)
    b = _cluster(x=5.0, y=5.0)
    tracker.update([a, b], now=0.0)

    # Tylko 'a' potwierdzony w tym ticku - 'b' powinien wciaz przetrwac
    # (w oknie tolerancji), oba widoczne.
    result = tracker.update([a], now=1.0)

    assert len(result) == 2


def test_match_threshold_grows_with_distance_from_sensor():
    # Domyslne parametry (base=0.15, slope=0.03): przy zasiegu ~10m prog to
    # ~0.15+0.03*10=0.45m - przesuniecie 0.4m powinno sie wciaz dopasowac,
    # mimo ze przy zasiegu ~0m (prog ~0.15m) TAKIE SAMO przesuniecie by nie
    # przeszlo.
    tracker_far = ClusterPersistenceTracker()
    far1 = _cluster(x=10.0, y=0.0)
    tracker_far.update([far1], now=0.0)
    far2 = _cluster(x=10.4, y=0.0)
    result_far = tracker_far.update([far2], now=0.2)
    assert len(result_far) == 1
    assert result_far[0].centroid_x == far2.centroid_x  # dopasowano, zaktualizowano

    tracker_near = ClusterPersistenceTracker()
    near1 = _cluster(x=0.0, y=0.0)
    tracker_near.update([near1], now=0.0)
    near2 = _cluster(x=0.4, y=0.0)
    result_near = tracker_near.update([near2], now=0.2)
    # Blisko czujnika ten sam przeskok (0.4m) przekracza waski prog - NIE
    # dopasowano, oba widoczne jako osobne obiekty.
    assert len(result_near) == 2
