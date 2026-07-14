function nextRotationClass(current) {
  return current === 'rotated' ? '' : 'rotated';
}

function initCameraTab(context) {
  const videoEl = document.getElementById('video');
  const startBtn = document.getElementById('camera-start');
  const stopBtn = document.getElementById('camera-stop');
  const rotateBtn = document.getElementById('camera-rotate');
  const captureBtn = document.getElementById('camera-capture');

  startBtn.addEventListener('click', () => {
    context.sendControl({ type: 'stream', enabled: true });
  });

  stopBtn.addEventListener('click', () => {
    context.sendControl({ type: 'stream', enabled: false });
  });

  rotateBtn.addEventListener('click', () => {
    videoEl.className = nextRotationClass(videoEl.className);
  });

  captureBtn.addEventListener('click', () => {
    const canvas = document.createElement('canvas');
    canvas.width = videoEl.naturalWidth || videoEl.width;
    canvas.height = videoEl.naturalHeight || videoEl.height;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(videoEl, 0, 0);

    canvas.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `frame_${Date.now()}.jpg`;
      a.click();
      URL.revokeObjectURL(url);
    }, 'image/jpeg');
  });
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { nextRotationClass, initCameraTab };
}
