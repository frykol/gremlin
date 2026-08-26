function colorDetectionStatusLabel(detected) {
  return detected ? 'TAK' : 'NIE';
}

function initColorDetectionTab(context) {
  const statusEl = document.getElementById('color-detection-status');
  const ratioEl = document.getElementById('color-detection-ratio');
  const previewEl = document.getElementById('color-detection-preview');
  if (!statusEl) return;

  context.onControlMessage((data) => {
    if (data.type !== 'color_detection_state') return;

    statusEl.textContent = colorDetectionStatusLabel(data.detected);
    statusEl.className = `bands-status ${data.detected ? 'bands-status-yes' : 'bands-status-no'}`;

    if (ratioEl) ratioEl.textContent = `${(data.blue_ratio * 100).toFixed(1)}%`;
    if (previewEl && data.debug_frame) {
      previewEl.src = `data:image/jpeg;base64,${data.debug_frame}`;
    }
  });

  setInterval(() => {
    context.sendControl({ type: 'get_color_detection_state' });
  }, 200);
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { colorDetectionStatusLabel, initColorDetectionTab };
}
