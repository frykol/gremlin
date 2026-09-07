// gremlin/lidar_viewer/frontend/js/metrics_panel.js
function createMetricsPanel(containerEl) {
  let frameCount = 0;
  let lastFpsSample = performance.now();
  let renderFps = 0;

  function tickRenderFrame() {
    frameCount++;
    const now = performance.now();
    const elapsed = now - lastFpsSample;
    if (elapsed >= 1000) {
      renderFps = (frameCount * 1000) / elapsed;
      frameCount = 0;
      lastFpsSample = now;
    }
  }

  // Backend wysyla sentinel < 0 (ws_server.LATENCY_NOT_AVAILABLE), gdy
  // opoznienia nie da sie sensownie policzyc - w trybie replay `stamp`
  // pochodzi z nagrania, wiec `now - stamp` to wiek nagrania (rzedu 1e12 ms),
  // nie pomiar. Renderujemy wtedy "N/A" zamiast liczby udajacej pomiar.
  function formatLatency(latencyMs) {
    if (typeof latencyMs !== 'number' || !Number.isFinite(latencyMs) || latencyMs < 0) {
      return 'N/A';
    }
    return `${latencyMs.toFixed(1)}ms`;
  }

  function updateFromServerMetrics({ fps, pointsInWindow, latencyMs }) {
    containerEl.textContent =
      `punkty: ${pointsInWindow} | scan FPS: ${fps.toFixed(1)} | render FPS: ${renderFps.toFixed(1)} | opoznienie: ${formatLatency(latencyMs)}`;
  }

  return { tickRenderFrame, updateFromServerMetrics, formatLatency };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { createMetricsPanel };
} else {
  window.createMetricsPanel = createMetricsPanel;
}
