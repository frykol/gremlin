from backend.lidar.anomaly_scorer import ClusterAnomalyScorer, extract_features
from backend.lidar.obstacle_clustering import ObstacleCluster


def _cluster(point_count=20, mean_intensity=150.0, intensity_std=10.0, x=0.5, y=0.5, size=0.1):
    return ObstacleCluster(
        x_min=x, x_max=x + size,
        y_min=y, y_max=y + size,
        z_min=0.1, z_max=0.3,
        centroid_x=x + size / 2, centroid_y=y + size / 2, centroid_z=0.2,
        point_count=point_count,
        mean_intensity=mean_intensity,
        intensity_std=intensity_std,
    )


def test_extract_features_shape_and_values():
    c = _cluster(point_count=25, mean_intensity=120.0, intensity_std=8.0, x=1.0, y=0.0, size=0.2)
    features = extract_features(c)
    assert features.shape == (6,)
    assert features[0] == 25  # point_count
    assert features[3] == 120.0  # mean_intensity
    assert features[4] == 8.0  # intensity_std


def test_score_returns_neutral_before_fitting():
    scorer = ClusterAnomalyScorer(min_history=50)
    clusters = [_cluster() for _ in range(5)]

    assert not scorer.is_fitted
    scores = scorer.score(clusters)

    assert scores == [0.5] * 5


def test_score_empty_list_returns_empty():
    scorer = ClusterAnomalyScorer(min_history=50)
    assert scorer.score([]) == []


def test_fit_fails_with_too_little_history():
    scorer = ClusterAnomalyScorer(min_history=50)
    clusters = [_cluster() for _ in range(10)]

    ok = scorer.fit(clusters)

    assert not ok
    assert not scorer.is_fitted


def test_fit_succeeds_with_enough_history():
    scorer = ClusterAnomalyScorer(min_history=20)
    clusters = [_cluster(point_count=15 + i % 10) for i in range(30)]

    ok = scorer.fit(clusters)

    assert ok
    assert scorer.is_fitted


def test_build_fitted_model_returns_none_with_too_little_history():
    scorer = ClusterAnomalyScorer(min_history=50)
    clusters = [_cluster() for _ in range(10)]

    model = scorer.build_fitted_model(clusters)

    assert model is None
    assert not scorer.is_fitted  # build_fitted_model NIE modyfikuje stanu


def test_build_fitted_model_does_not_mutate_instance_state():
    scorer = ClusterAnomalyScorer(min_history=20)
    clusters = [_cluster(point_count=15 + i % 10) for i in range(30)]

    model = scorer.build_fitted_model(clusters)

    # Model zwrocony, ale instancja scorera NIE zostala zmieniona - to jest
    # cel tego rozbicia (bezpieczne wywolanie fit w tle bez wplywu na
    # rownolegle score() na aktualnym self._model).
    assert model is not None
    assert not scorer.is_fitted


def test_apply_fitted_model_activates_it():
    scorer = ClusterAnomalyScorer(min_history=20)
    clusters = [_cluster(point_count=15 + i % 10) for i in range(30)]

    model = scorer.build_fitted_model(clusters)
    assert not scorer.is_fitted

    scorer.apply_fitted_model(model)

    assert scorer.is_fitted
    # I faktycznie dziala do scoringu.
    scores = scorer.score([_cluster()])
    assert len(scores) == 1
    assert scores[0] != 0.5


def test_build_then_apply_equivalent_to_fit():
    scorer_a = ClusterAnomalyScorer(min_history=20, random_state=0)
    scorer_b = ClusterAnomalyScorer(min_history=20, random_state=0)
    clusters = [_cluster(point_count=15 + i % 10, x=i * 0.1) for i in range(30)]

    scorer_a.fit(clusters)
    model = scorer_b.build_fitted_model(clusters)
    scorer_b.apply_fitted_model(model)

    probe = [_cluster(point_count=18, x=0.5)]
    assert scorer_a.score(probe) == scorer_b.score(probe)


def test_scores_use_the_full_range_not_a_narrow_band():
    # Regresja: wynik byl sigmoida ze staloczynnikowym wzmocnieniem 5.0,
    # dobranym przy zalozeniu (z komentarza w kodzie), ze decision_function
    # daje "typowo w przyblizeniu [-0.5, 0.5]". Zmierzone na 927 klastrach
    # z ZYWEGO lidaru: faktyczny zakres to [-0.157, 0.078], czyli ~10x
    # wezszy. Wyniki sciskaly sie do [0.31, 0.60] - wskaznik wygladal jak
    # stala 0.5, a prog "nietypowe < 0.3" w UI nie mogl sie odpalic NIGDY.
    # Ranga percentylowa wzgledem rozkladu treningowego jest z definicji
    # rozlozona na calym [0,1], niezaleznie od skali surowych ocen.
    scorer = ClusterAnomalyScorer(min_history=20, random_state=0)
    history = [
        _cluster(point_count=15 + (i % 30), mean_intensity=140 + (i % 40),
                 intensity_std=5 + (i % 10), x=(i % 20) * 0.3, y=0.5)
        for i in range(200)
    ]
    scorer.fit(history)

    scores = scorer.score(history)

    assert min(scores) < 0.15, f"brak niskich ocen, min={min(scores):.3f}"
    assert max(scores) > 0.85, f"brak wysokich ocen, max={max(scores):.3f}"


def test_novel_cluster_scores_near_zero():
    # Sedno przydatnosci: obiekt spoza rozkladu treningowego ma dostac
    # ocene blisko 0 (mniej typowy niz cokolwiek widzianego), a nie
    # "gdzies kolo 0.4", jak w poprzedniej wersji.
    scorer = ClusterAnomalyScorer(min_history=20, random_state=0)
    history = [
        _cluster(point_count=15 + (i % 10), mean_intensity=140 + (i % 20),
                 intensity_std=8, x=(i % 10) * 0.2, y=0.5)
        for i in range(120)
    ]
    scorer.fit(history)

    novel = _cluster(point_count=5000, mean_intensity=255, intensity_std=120,
                     x=60.0, y=60.0, size=9.0)

    # Dolny ogon rozkladu. Poprzednia wersja (sigmoida) dawala tu 0.38,
    # czyli praktycznie "nie wiem" - stad w ogole ten test.
    assert scorer.score([novel])[0] < 0.1


def test_repeated_identical_clusters_are_not_systematically_underrated():
    # W statycznej scenie ten sam klaster powtarza sie w historii dziesiatki
    # razy. Ranga liczona sama granica lewa (side="left") zanizalaby go o
    # cala wiazke remisow - najbardziej typowy klaster nie mogl osiagnac
    # wysokiej oceny. Srodek wiazki to naprawia.
    scorer = ClusterAnomalyScorer(min_history=20, random_state=0)
    # Historia: jeden bardzo czesty klaster + garstka roznych.
    common = [_cluster(point_count=20, x=1.0, y=1.0) for _ in range(150)]
    varied = [_cluster(point_count=10 + i * 3, x=i * 0.7, y=2.0) for i in range(20)]
    scorer.fit(common + varied)

    # Zmierzone na tej scenie: side="left" dawal 0.118 - NAJCZESTSZY obiekt
    # w calej scenie ladowal w dolnych 12%, czyli praktycznie oznaczony jako
    # "nieznany modelowi". Srodek wiazki daje 0.559.
    #
    # Uwaga: 0.559, a nie ~1.0, jest tu POPRAWNE. Gdy 88% historii to jedna
    # identyczna wartosc, jej ranga percentylowa z definicji lezy w srodku
    # wlasnej wiazki remisow - nie da sie byc "bardziej typowym niz sam
    # sobie". Sygnalem pozostaje dolny ogon (patrz
    # test_novel_cluster_scores_near_zero).
    score = scorer.score([_cluster(point_count=20, x=1.0, y=1.0)])[0]

    assert score > 0.3, f"najczestszy klaster trafil w dolny ogon: {score:.3f}"


def test_scores_stay_within_unit_interval():
    scorer = ClusterAnomalyScorer(min_history=20, random_state=0)
    history = [_cluster(point_count=15 + (i % 10), x=i * 0.1) for i in range(60)]
    scorer.fit(history)

    probes = [
        _cluster(point_count=18, x=0.5),
        _cluster(point_count=99999, x=500.0, size=50.0),
        _cluster(point_count=1, x=-500.0, size=0.001),
    ]

    for s in scorer.score(probes):
        assert 0.0 <= s <= 1.0


def test_typical_cluster_scores_higher_than_extreme_outlier():
    scorer = ClusterAnomalyScorer(min_history=20, random_state=0)
    # "Normalna" historia - male, zwarte klastry blisko robota.
    history = [
        _cluster(point_count=15 + (i % 10), mean_intensity=140 + (i % 20), intensity_std=8, x=i * 0.05, y=0.5)
        for i in range(60)
    ]
    scorer.fit(history)

    typical = _cluster(point_count=18, mean_intensity=145, intensity_std=9, x=0.5, y=0.5)
    # Skrajnie inny: gigantyczna liczba punktow, ekstremalna intensywnosc,
    # bardzo daleko - powinien wypasc jako mniej typowy.
    outlier = _cluster(point_count=5000, mean_intensity=255, intensity_std=100, x=50.0, y=50.0, size=5.0)

    scores = scorer.score([typical, outlier])

    assert scores[0] > scores[1]
