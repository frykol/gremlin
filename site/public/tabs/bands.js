function bandStatusLabel(bothDetected) {
  return bothDetected ? 'TAK' : 'NIE';
}

function initBandsTab(context) {
  const statusEl = document.getElementById('bands-status');
  const leftEl = document.getElementById('bands-left');
  const rightEl = document.getElementById('bands-right');
  const previewEl = document.getElementById('bands-preview');
  if (!statusEl) return;

  context.onControlMessage((data) => {
    if (data.type !== 'band_detection_state') return;

    statusEl.textContent = bandStatusLabel(data.both_detected);
    statusEl.className = `bands-status ${data.both_detected ? 'bands-status-yes' : 'bands-status-no'}`;

    if (leftEl) leftEl.textContent = data.left ? 'TAK' : 'NIE';
    if (rightEl) rightEl.textContent = data.right ? 'TAK' : 'NIE';
    if (previewEl && data.debug_frame) {
      previewEl.src = `data:image/jpeg;base64,${data.debug_frame}`;
    }
  });

  setInterval(() => {
    context.sendControl({ type: 'get_band_detection_state' });
  }, 200);
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { bandStatusLabel, initBandsTab };
}
