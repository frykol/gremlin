function colorDetectionStatusLabel(detected) {
  return detected ? 'TAK' : 'NIE';
}

function greenOnYellowStatusLabel(detected) {
  return detected ? 'TAK' : 'NIE';
}

function initColorDetectionTab(context) {
  const statusEl = document.getElementById('color-detection-status');
  const ratioEl = document.getElementById('color-detection-ratio');
  const blobCountEl = document.getElementById('color-detection-blob-count');
  const yellowCountEl = document.getElementById('color-detection-yellow-count');
  const bandStatusEl = document.getElementById('color-detection-band-status');
  const previewEl = document.getElementById('color-detection-preview');
  const followToggle = document.getElementById('follow-band-toggle');
  if (!statusEl) return;

  if (followToggle) {
    followToggle.addEventListener('change', () => {
      context.sendControl({ type: 'set_follow_band_mode', enabled: followToggle.checked });
    });
  }

  context.onControlMessage((data) => {
    if (data.type !== 'color_detection_state') return;

    statusEl.textContent = colorDetectionStatusLabel(data.detected);
    statusEl.className = `bands-status ${data.detected ? 'bands-status-yes' : 'bands-status-no'}`;

    if (ratioEl) ratioEl.textContent = `${(data.blue_ratio * 100).toFixed(1)}%`;
    if (blobCountEl) blobCountEl.textContent = (data.blue_bboxes || []).length;
    if (yellowCountEl) yellowCountEl.textContent = (data.yellow_bboxes || []).length;
    if (bandStatusEl) bandStatusEl.textContent = greenOnYellowStatusLabel(data.green_on_yellow_detected);
    if (previewEl && data.debug_frame) {
      previewEl.src = `data:image/jpeg;base64,${data.debug_frame}`;
    }
  });

  setInterval(() => {
    context.sendControl({ type: 'get_color_detection_state' });
  }, 200);
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { colorDetectionStatusLabel, greenOnYellowStatusLabel, initColorDetectionTab };
}
