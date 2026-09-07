function initLidarTab() {
    const canvas = document.getElementById('viewer-canvas');
    const banner = document.getElementById('connection-banner');
    const imuPanel = createImuPanel(document.getElementById('imu-panel'));
    const metricsPanel = createMetricsPanel(document.getElementById('metrics-panel'));
    if (!canvas) return;

    const viewer = createViewer(canvas, 65000);
    const backendOrigin = `${window.location.protocol}//${window.location.hostname}:8767`;
    const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.hostname}:8767/ws/lidar`;

    const radarCanvas = document.getElementById('obstacle-radar-canvas');
    const radar = radarCanvas ? createObstacleRadar(radarCanvas, { rangeM: 8 }) : null;
    const obstacleSummaryEl = document.getElementById('obstacle-summary-panel');

    // Tekstowy dowod dzialania ClusterAnomalyScorer (backend/lidar/
    // anomaly_scorer.py) - dopoki model sie nie wytrenuje (potrzebuje
    // min. 50 probek w historii), wszystkie klastry maja anomalyScore
    // dokladnie 0.5 ("brak oceny"), co odrozniamy od realnych wynikow.
    //
    // anomalyScore to RANGA PERCENTYLOWA wzgledem tego, co model widzial w
    // treningu (0 = mniej typowy niz cokolwiek widzianego). Dlatego NIE
    // pokazujemy tu sredniej: przy randze percentylowej srednia z definicji
    // siedzi kolo 0.5 niezaleznie od sceny, wiec nic nie wnosi. Sygnalem
    // jest MINIMUM - "czy pojawilo sie cos, czego model nie zna".
    const ANOMALY_LOW_TAIL = 0.1;

    function updateObstacleSummary(clusters) {
        if (!obstacleSummaryEl) return;
        if (!clusters.length) {
            obstacleSummaryEl.textContent = 'brak wykrytych obiektow';
            return;
        }
        const scores = clusters.map((c) => c.anomalyScore);
        const allNeutral = scores.every((s) => Math.abs(s - 0.5) < 1e-6);
        if (allNeutral) {
            obstacleSummaryEl.textContent =
                `klastry: ${clusters.length} | model anomalii: uczy sie (zbiera historie)...`;
            return;
        }
        const least = Math.min(...scores);
        const unusual = scores.filter((s) => s < ANOMALY_LOW_TAIL).length;
        obstacleSummaryEl.textContent =
            `klastry: ${clusters.length} | najmniej typowy: ${least.toFixed(2)} | ` +
            `nieznane modelowi (<${ANOMALY_LOW_TAIL}): ${unusual}`;
    }

    // Suwaki do recznej DOREGULACJI orientacji ponad wbudowana baze
    // (BASE_TILT_* w pointcloud.js, dobrana na zywo patrzac na prawdziwy
    // pokoj) - 0 na suwaku = sama baza, bez dodatkowej korekty. Klucze
    // localStorage maja sufiks V2, zeby stare wartosci zapisane pod starą
    // semantyka (0 = brak korekty) nie nalozyly sie podwojnie na nowa baze.
    const AXES = [
        { key: 'x', slider: 'lidar-tilt-x-slider', value: 'lidar-tilt-x-value', win: 'LIDAR_TILT_X_DEG', storage: 'lidarTiltXDegV2', default: 0 },
        { key: 'y', slider: 'lidar-tilt-y-slider', value: 'lidar-tilt-y-value', win: 'LIDAR_TILT_Y_DEG', storage: 'lidarTiltYDegV2', default: 0 },
        { key: 'z', slider: 'lidar-tilt-z-slider', value: 'lidar-tilt-z-value', win: 'LIDAR_TILT_Z_DEG', storage: 'lidarTiltZDegV2', default: 0 },
    ];

    AXES.forEach((axis) => {
        const sliderEl = document.getElementById(axis.slider);
        const valueEl = document.getElementById(axis.value);
        if (!sliderEl) return;

        const saved = localStorage.getItem(axis.storage);
        if (saved !== null) {
            sliderEl.value = saved;
            window[axis.win] = parseFloat(saved);
            if (valueEl) valueEl.textContent = `${saved}°`;
        }
        sliderEl.addEventListener('input', () => {
            const deg = parseFloat(sliderEl.value);
            window[axis.win] = deg;
            if (valueEl) valueEl.textContent = `${deg}°`;
            localStorage.setItem(axis.storage, String(deg));
        });
    });

    const resetBtn = document.getElementById('lidar-tilt-reset');
    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            AXES.forEach((axis) => {
                const sliderEl = document.getElementById(axis.slider);
                const valueEl = document.getElementById(axis.value);
                if (sliderEl) sliderEl.value = axis.default;
                if (valueEl) valueEl.textContent = `${axis.default}°`;
                window[axis.win] = axis.default;
                localStorage.setItem(axis.storage, String(axis.default));
            });
        });
    }

    function showDisconnected() {
        banner.textContent = 'Rozłączono z backendem LiDAR.';
        banner.classList.add('visible');
    }

    async function startAndConnect() {
        try {
            const response = await fetch(`${backendOrigin}/api/lidar/start`, { method: 'POST' });
            if (!response.ok) throw new Error(`LiDAR start failed: ${response.status}`);
            window.wsClient.connect(wsUrl, {
                onScan: ({ points, pointCount }) => viewer.setPoints(points, pointCount),
                onImu: (imu) => {
                    imuPanel.update(imu);
                    viewer.setImuOrientation(imu.quaternion);
                },
                onMetrics: (metrics) => metricsPanel.updateFromServerMetrics(metrics),
                onObstacles: ({ clusters }) => {
                    viewer.setObstacles(clusters);
                    if (radar) radar.render(clusters);
                    updateObstacleSummary(clusters);
                },
                onDisconnect: showDisconnected,
            });
        } catch (error) {
            showDisconnected();
            console.error(error);
        }
    }

    startAndConnect();

    function updateRenderMetrics() {
        metricsPanel.tickRenderFrame();
        requestAnimationFrame(updateRenderMetrics);
    }

    updateRenderMetrics();
    viewer.render();
}
