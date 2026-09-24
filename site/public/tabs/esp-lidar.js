function initEspLidarTab() {
    const canvas = document.getElementById('esp-lidar-viewer-canvas');
    const banner = document.getElementById('esp-lidar-connection-banner');
    const metricsEl = document.getElementById('esp-lidar-metrics-panel');
    if (!canvas) return;

    const viewer = createEspViewer(canvas);
    const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.hostname}:8769/ws/esp_lidar`;

    // Suwaki recznej korekty montazu. Domyslne wartosci przejete WPROST z
    // zakladki Lidar (site/public/lidar/js/pointcloud.js BASE_TILT_X/Y/Z_DEG
    // = -122/19/-11) na wyrazna prosbe usera - to sa katy dobrane RECZNIE
    // dla montazu Unitree L1 patrzac na zywo na prawdziwy pokoj, NIE
    // zgadywane/wyliczone dla ESP. Prawdopodobnie beda wymagaly ponownego
    // strojenia na zywo dla innego montazu ESP, ale to sprawdzony punkt
    // startowy zamiast kolejnego zgadywania.
    //
    // WAZNE: korekta jest teraz stosowana przez viewer.setManualTilt() na
    // poziomie CALEGO obiektu chmury (patrz komentarz w
    // esp_lidar/js/pointcloud.js) - kazda zmiana suwaka natychmiast
    // dziala na WSZYSTKICH punktach aktualnej ramki.
    // Wczesniejsza wersja piekla obrot per-punkt przy zapisie, wiec zmiana
    // suwaka dotyczyla tylko nowych punktow - stare zostawaly zamrozone w
    // poprzedniej orientacji i obraz nigdy nie wygladal poziomo,
    // niezaleznie od ustawien.
    const AXES = [
        { key: 'x', slider: 'esp-lidar-tilt-x-slider', value: 'esp-lidar-tilt-x-value', storage: 'espLidarTiltXDeg', default: -122 },
        { key: 'y', slider: 'esp-lidar-tilt-y-slider', value: 'esp-lidar-tilt-y-value', storage: 'espLidarTiltYDeg', default: 19 },
        { key: 'z', slider: 'esp-lidar-tilt-z-slider', value: 'esp-lidar-tilt-z-value', storage: 'espLidarTiltZDeg', default: -11 },
    ];
    const tiltDeg = { x: 0, y: 0, z: 0 };

    function applyManualTiltFromState() {
        viewer.setManualTilt(tiltDeg.x, tiltDeg.y, tiltDeg.z);
    }

    AXES.forEach((axis) => {
        const sliderEl = document.getElementById(axis.slider);
        const valueEl = document.getElementById(axis.value);
        if (!sliderEl) return;

        const saved = localStorage.getItem(axis.storage);
        if (saved !== null) {
            sliderEl.value = saved;
        }
        const initialDeg = parseFloat(sliderEl.value);
        tiltDeg[axis.key] = initialDeg;
        if (valueEl) valueEl.textContent = `${initialDeg}°`;
        sliderEl.addEventListener('input', () => {
            const deg = parseFloat(sliderEl.value);
            tiltDeg[axis.key] = deg;
            if (valueEl) valueEl.textContent = `${deg}°`;
            localStorage.setItem(axis.storage, String(deg));
            if (!imuActive) applyManualTiltFromState();
        });
    });

    const resetBtn = document.getElementById('esp-lidar-tilt-reset');
    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            AXES.forEach((axis) => {
                const sliderEl = document.getElementById(axis.slider);
                const valueEl = document.getElementById(axis.value);
                if (sliderEl) sliderEl.value = axis.default;
                if (valueEl) valueEl.textContent = `${axis.default}°`;
                tiltDeg[axis.key] = axis.default;
                localStorage.setItem(axis.storage, String(axis.default));
            });
            if (!imuActive) applyManualTiltFromState();
            IMU_OFFSET_AXES.forEach((axis) => {
                const sliderEl = document.getElementById(axis.slider);
                const valueEl = document.getElementById(axis.value);
                if (sliderEl) sliderEl.value = axis.default;
                if (valueEl) valueEl.textContent = `${axis.default}°`;
                imuOffsetDeg[axis.key] = axis.default;
                localStorage.setItem(axis.storage, String(axis.default));
            });
            applyImuOffsetFromState();
        });
    }

    // Gdy ESP zacznie wysylac IMU (message type 2 - quaternion, patrz
    // esp_rasp_test/PROTOCOL.txt), orientacja z IMU obraca CALY obiekt
    // chmury punktow (viewer.setImuOrientation) zamiast recznych suwakow -
    // dokladniejsze, bo montaz jest staly, a IMU mierzy realny kat wzgledem
    // grawitacji zamiast zgadywania. Przelacznik pozwala wrocic do recznej
    // kalibracji suwakami, gdyby IMU jeszcze nie dzialalo albo dawalo zle
    // wyniki.
    const imuAutoToggle = document.getElementById('esp-lidar-imu-auto-toggle');
    let imuActive = false;

    // Stala doregulacja X/Y/Z doklejana do KAZDEGO odczytu IMU (patrz
    // viewer.setImuOffsetDeg) - IMU mierzy swoja wlasna orientacje, ale
    // moze byc przykrecone do lidaru pod jakims wlasnym, stalym katem w
    // KAZDEJ z 3 osi, ktorego samo nie widzi. X=-30 stopni to punkt
    // startowy z rozmowy z userem ("na pewno blisko"), Y/Z startuja od 0 -
    // suwaki pozwalaja doprecyzowac wszystko na zywo, bez zgadywania w kodzie.
    const IMU_OFFSET_AXES = [
        { key: 'x', slider: 'esp-lidar-imu-offset-x-slider', value: 'esp-lidar-imu-offset-x-value', storage: 'espLidarImuOffsetXDeg', default: -30 },
        { key: 'y', slider: 'esp-lidar-imu-offset-y-slider', value: 'esp-lidar-imu-offset-y-value', storage: 'espLidarImuOffsetYDeg', default: 0 },
        { key: 'z', slider: 'esp-lidar-imu-offset-z-slider', value: 'esp-lidar-imu-offset-z-value', storage: 'espLidarImuOffsetZDeg', default: 0 },
    ];
    const imuOffsetDeg = { x: -30, y: 0, z: 0 };

    function applyImuOffsetFromState() {
        viewer.setImuOffsetDeg(imuOffsetDeg.x, imuOffsetDeg.y, imuOffsetDeg.z);
    }

    IMU_OFFSET_AXES.forEach((axis) => {
        const sliderEl = document.getElementById(axis.slider);
        const valueEl = document.getElementById(axis.value);
        if (!sliderEl) return;

        const saved = localStorage.getItem(axis.storage);
        if (saved !== null) sliderEl.value = saved;
        const initialDeg = parseFloat(sliderEl.value);
        imuOffsetDeg[axis.key] = initialDeg;
        if (valueEl) valueEl.textContent = `${initialDeg}°`;
        sliderEl.addEventListener('input', () => {
            const deg = parseFloat(sliderEl.value);
            imuOffsetDeg[axis.key] = deg;
            if (valueEl) valueEl.textContent = `${deg}°`;
            localStorage.setItem(axis.storage, String(deg));
            applyImuOffsetFromState();
        });
    });
    applyImuOffsetFromState();

    function setSlidersDisabled(disabled) {
        AXES.forEach((axis) => {
            const sliderEl = document.getElementById(axis.slider);
            if (sliderEl) sliderEl.disabled = disabled;
        });
    }

    function useManualTilt() {
        imuActive = false;
        setSlidersDisabled(false);
        applyManualTiltFromState();
    }

    if (imuAutoToggle) {
        imuAutoToggle.addEventListener('change', () => {
            if (!imuAutoToggle.checked) useManualTilt();
            // wlaczenie z powrotem samo w sobie nic nie robi - poczeka na
            // kolejna ramke IMU (patrz applyImu nizej)
        });
    }
    useManualTilt(); // stan startowy, zanim przyjdzie ewentualnie pierwsza ramka IMU

    function applyImu(imu) {
        if (!imuAutoToggle || !imuAutoToggle.checked) return;
        if (!imuActive) {
            imuActive = true;
            setSlidersDisabled(true);
        }
        viewer.setImuOrientation(imu.quaternion);
    }

    const controlUrl = `${window.location.protocol === 'https:' ? 'https:' : 'http:'}//${window.location.hostname}:8769`;
    const controlStatus = document.getElementById('esp-lidar-control-status');
    const controlMessage = document.getElementById('esp-lidar-control-message');
    const streamMask = document.getElementById('esp-lidar-stream-mask');
    const controlInputs = [
        document.getElementById('esp-lidar-active'),
        document.getElementById('esp-lidar-fusion'),
        document.getElementById('esp-lidar-cloud'),
        document.getElementById('esp-lidar-imu'),
        document.getElementById('esp-lidar-obstacles'),
        streamMask,
    ].filter(Boolean);
    const RESULT_NAMES = {
        0: 'OK',
        1: 'BAD_COMMAND',
        2: 'BAD_ARGUMENT',
        3: 'UNSUPPORTED',
        4: 'INTERNAL_ERROR',
    };

    function setControlBusy(busy) {
        controlInputs.forEach((input) => { input.disabled = busy; });
        document.querySelectorAll('#esp-lidar-control button').forEach((button) => {
            button.disabled = busy;
        });
    }

    function applyAck(ack) {
        const active = document.getElementById('esp-lidar-active');
        const fusion = document.getElementById('esp-lidar-fusion');
        const cloud = document.getElementById('esp-lidar-cloud');
        const imu = document.getElementById('esp-lidar-imu');
        const obstacles = document.getElementById('esp-lidar-obstacles');
        if (active) active.checked = Boolean(ack.lidar_active);
        if (fusion) fusion.checked = Boolean(ack.fusion_enabled);
        if (cloud) cloud.checked = Boolean(ack.stream_mask & 1);
        if (imu) imu.checked = Boolean(ack.stream_mask & 2);
        if (obstacles) obstacles.checked = Boolean(ack.stream_mask & 4);
        if (streamMask) streamMask.value = String(ack.stream_mask);
        if (controlStatus) {
            controlStatus.textContent = `${RESULT_NAMES[ack.result] || `RESULT_${ack.result}`} | uptime ${Math.floor(ack.uptime_ms / 1000)} s`;
        }
        if (controlMessage) controlMessage.textContent = ack.result === 0 ? '' : `ESP odrzucił komendę: ${RESULT_NAMES[ack.result] || ack.result}`;
    }

    async function sendControlCommand(command, args = []) {
        setControlBusy(true);
        if (controlMessage) controlMessage.textContent = 'wysyłanie...';
        try {
            const response = await fetch(`${controlUrl}/api/esp_lidar/command`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ command, args }),
            });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
            applyAck(payload);
        } catch (error) {
            if (controlStatus) controlStatus.textContent = 'brak połączenia';
            if (controlMessage) controlMessage.textContent = `Sterowanie ESP: ${error.message}`;
        } finally {
            setControlBusy(false);
        }
    }

    async function refreshControlStatus() {
        setControlBusy(true);
        if (controlMessage) controlMessage.textContent = 'pobieranie statusu...';
        try {
            const response = await fetch(`${controlUrl}/api/esp_lidar/status`);
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
            applyAck(payload);
        } catch (error) {
            if (controlStatus) controlStatus.textContent = 'brak połączenia';
            if (controlMessage) controlMessage.textContent = `Status ESP: ${error.message}`;
        } finally {
            setControlBusy(false);
        }
    }

    const controlBindings = [
        ['esp-lidar-active', 'set_lidar_active'],
        ['esp-lidar-fusion', 'set_fusion_active'],
        ['esp-lidar-cloud', 'set_cloud_active'],
        ['esp-lidar-imu', 'set_imu_active'],
        ['esp-lidar-obstacles', 'set_obstacles_active'],
    ];
    controlBindings.forEach(([id, command]) => {
        const input = document.getElementById(id);
        if (input) input.addEventListener('change', () => sendControlCommand(command, [input.checked ? 1 : 0]));
    });
    if (streamMask) streamMask.addEventListener('change', () => sendControlCommand('set_stream_mask', [Number(streamMask.value)]));
    const pingButton = document.getElementById('esp-lidar-ping');
    if (pingButton) pingButton.addEventListener('click', () => sendControlCommand('ping'));
    const refreshButton = document.getElementById('esp-lidar-refresh-status');
    if (refreshButton) refreshButton.addEventListener('click', refreshControlStatus);
    const clearButton = document.getElementById('esp-lidar-clear-history');
    if (clearButton) clearButton.addEventListener('click', () => sendControlCommand('clear_history'));
    refreshControlStatus();

    function showDisconnected() {
        if (!banner) return;
        banner.textContent = 'Rozłączono z serwisem ESP LiDAR.';
        banner.classList.add('visible');
    }

    function showConnected() {
        if (!banner) return;
        banner.classList.remove('visible');
    }

    function connect() {
        // Ten sam dekoder WS co zakladka Lidar (window.wsClient) - format
        // Scan i IMU z ESP jest celowo identyczny jak backend/lidar/ws_server.
        window.wsClient.connect(wsUrl, {
            onScan: ({ points, pointCount }) => {
                showConnected();
                viewer.setPoints(points, pointCount);
            },
            onObstacles: ({ clusters }) => {
                showConnected();
                viewer.setObstacles(clusters);
            },
            onImu: applyImu,
            onMetrics: (metrics) => {
                if (!metricsEl) return;
                const rate = metrics.fps || 0;
                const points = metrics.pointsInWindow || 0;
                metricsEl.textContent = `pakiety/s: ${rate.toFixed(1)} | punkty w ramce: ${points}`;
            },
            onDisconnect: showDisconnected,
        });
    }

    connect();
    viewer.render();
}
