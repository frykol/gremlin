// gremlin/lidar_viewer/frontend/js/main.js

/**
 * Backend serwuje TE strone i WS z tego samego portu (backend/app.py +
 * backend/static_files.py), wiec URL WS wynika wprost z window.location.
 * Fallback jest tylko dla przypadku otwarcia pliku przez file:// - wtedy
 * location nie niesie zadnego hosta.
 */
function deriveWsUrl() {
  const loc = window.location;
  if (loc.protocol === 'http:' || loc.protocol === 'https:') {
    const scheme = loc.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${scheme}//${loc.hostname}:8767`;
  }
  return 'ws://localhost:8767';
}

window.addEventListener('DOMContentLoaded', () => {
  const canvas = document.getElementById('viewer-canvas');
  const imuEl = document.getElementById('imu-panel');
  const metricsEl = document.getElementById('metrics-panel');
  const bannerEl = document.getElementById('connection-banner');

  const MAX_POINTS = 200000; // gorny limit bufora - okno akumulacji jest po stronie backendu
  const viewer = createViewer(canvas, MAX_POINTS);
  const imuPanel = createImuPanel(imuEl);
  const metricsPanel = createMetricsPanel(metricsEl);

  function showDisconnected(info) {
    if (!bannerEl || bannerEl.classList.contains('visible')) return;
    const detail = info && info.reason === 'error' ? 'blad polaczenia' : 'polaczenie zamkniete';
    bannerEl.textContent = `Rozlaczono z backendem (${detail}) - dane nie sa aktualizowane. Odswiez strone.`;
    bannerEl.classList.add('visible');
  }

  const wsUrl = deriveWsUrl();
  window.wsClient.connect(wsUrl, {
    onScan: ({ points, pointCount }) => viewer.setPoints(points, pointCount),
    onImu: (imu) => {
      imuPanel.update(imu);
      viewer.setImuOrientation(imu.quaternion);
    },
    onMetrics: (metrics) => metricsPanel.updateFromServerMetrics(metrics),
    onDisconnect: showDisconnected,
  });

  function frame() {
    metricsPanel.tickRenderFrame();
    requestAnimationFrame(frame);
  }
  frame();

  viewer.render();
});
