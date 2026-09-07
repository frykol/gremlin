function pcmBase64ToFloat32(b64) {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  const int16 = new Int16Array(bytes.buffer);
  const float32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) {
    float32[i] = int16[i] / 32768;
  }
  return float32;
}

function levelFromInt16(int16) {
  let peak = 0;
  for (const s of int16) {
    peak = Math.max(peak, Math.abs(s));
  }
  return Math.min(100, Math.round((peak / 32768) * 100));
}

// Jesli zaplanowany odsluch wyprzedza realny czas o wiecej niz to, resetujemy
// harmonogram zamiast odtwarzac zalegly bufor od razu (np. po zawieszeniu
// AudioContext przez przegladarke w tle) - to byla przyczyna "wywalania sie"
// odsluchu po dluzszym czasie: nextStartTime rosl w nieskonczonosc niezaleznie
// od ctx.currentTime, wiec po powrocie leciala coraz dluzsza, coraz bardziej
// spozniona seria chunkow.
const MAX_SCHEDULE_DRIFT_SECONDS = 1.0;

function initMicTab(context) {
  const startBtn = document.getElementById('mic-start');
  const stopBtn = document.getElementById('mic-stop');
  const playbackCheckbox = document.getElementById('mic-playback');
  const levelBar = document.getElementById('mic-level-bar');
  const levelText = document.getElementById('mic-level-text');

  let audioCtx = null;
  let nextStartTime = 0;
  let sampleRate = 16000;

  function ensureAudioContext(rate) {
    if (!audioCtx || sampleRate !== rate) {
      if (audioCtx) {
        audioCtx.close();
      }
      audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: rate });
      nextStartTime = audioCtx.currentTime;
      sampleRate = rate;
    }
    if (audioCtx.state === 'suspended') {
      audioCtx.resume();
    }
    return audioCtx;
  }

  function playChunk(float32, rate) {
    if (!playbackCheckbox.checked) return;
    const ctx = ensureAudioContext(rate);

    if (nextStartTime - ctx.currentTime > MAX_SCHEDULE_DRIFT_SECONDS) {
      nextStartTime = ctx.currentTime;
    }

    const buffer = ctx.createBuffer(1, float32.length, rate);
    buffer.copyToChannel(float32, 0);

    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    source.onended = () => source.disconnect();

    const startAt = Math.max(nextStartTime, ctx.currentTime);
    source.start(startAt);
    nextStartTime = startAt + buffer.duration;
  }

  startBtn.addEventListener('click', () => {
    context.sendControl({ type: 'audio_stream', enabled: true });
  });

  stopBtn.addEventListener('click', () => {
    context.sendControl({ type: 'audio_stream', enabled: false });
  });

  context.onControlMessage((data) => {
    if (data.type !== 'audio_chunk') return;

    const binary = atob(data.samples);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    const int16 = new Int16Array(bytes.buffer);

    const level = levelFromInt16(int16);
    levelBar.style.height = `${level}%`;
    levelText.textContent = `chunk ${data.chunk_id} | poziom ${level}%`;

    const float32 = pcmBase64ToFloat32(data.samples);
    playChunk(float32, data.sample_rate || 16000);
  });

  initMicFilterControls(context);
  initMicNoiseProfileControls(context);
}

const NOISE_CALIBRATION_DURATION_MS = 2000;

function noiseProfileStatusLabel(status) {
  if (status.is_calibrating) return 'Nagrywanie profilu szumu…';
  if (status.has_profile) return 'Profil ustawiony';
  return 'Brak profilu';
}

function initMicNoiseProfileControls(context) {
  const calibrateBtn = document.getElementById('mic-calibrate-noise');
  const resetBtn = document.getElementById('mic-reset-noise');
  const statusEl = document.getElementById('mic-noise-profile-status');
  if (!calibrateBtn) return;

  calibrateBtn.addEventListener('click', () => {
    context.sendControl({ type: 'start_noise_profile_calibration' });
    setTimeout(() => {
      context.sendControl({ type: 'stop_noise_profile_calibration' });
    }, NOISE_CALIBRATION_DURATION_MS);
  });

  resetBtn.addEventListener('click', () => {
    context.sendControl({ type: 'reset_noise_profile' });
  });

  context.onControlMessage((data) => {
    if (data.type !== 'noise_profile_status') return;
    statusEl.textContent = noiseProfileStatusLabel(data);
  });

  context.sendControl({ type: 'get_noise_profile_status' });
}

function initMicFilterControls(context) {
  const lidarEnabled = document.getElementById('mic-filter-lidar-enabled');
  const lidarCenter = document.getElementById('mic-filter-lidar-center');
  const lidarWidth = document.getElementById('mic-filter-lidar-width');
  const lidarCenterValue = document.getElementById('mic-filter-lidar-center-value');
  const lidarWidthValue = document.getElementById('mic-filter-lidar-width-value');

  const motorEnabled = document.getElementById('mic-filter-motor-enabled');
  const motorCenter = document.getElementById('mic-filter-motor-center');
  const motorWidth = document.getElementById('mic-filter-motor-width');
  const motorCenterValue = document.getElementById('mic-filter-motor-center-value');
  const motorWidthValue = document.getElementById('mic-filter-motor-width-value');

  if (!lidarEnabled) return;

  let sendTimer = null;

  function applyConfigToControls(config) {
    lidarEnabled.checked = config.lidar_enabled;
    lidarCenter.value = config.lidar_center_hz;
    lidarWidth.value = config.lidar_width_hz;
    lidarCenterValue.textContent = config.lidar_center_hz;
    lidarWidthValue.textContent = config.lidar_width_hz;

    motorEnabled.checked = config.motor_enabled;
    motorCenter.value = config.motor_center_hz;
    motorWidth.value = config.motor_width_hz;
    motorCenterValue.textContent = config.motor_center_hz;
    motorWidthValue.textContent = config.motor_width_hz;
  }

  function sendConfig() {
    context.sendControl({
      type: 'set_audio_filter_config',
      lidar_enabled: lidarEnabled.checked,
      lidar_center_hz: Number(lidarCenter.value),
      lidar_width_hz: Number(lidarWidth.value),
      motor_enabled: motorEnabled.checked,
      motor_center_hz: Number(motorCenter.value),
      motor_width_hz: Number(motorWidth.value),
    });
  }

  function onSliderInput() {
    lidarCenterValue.textContent = lidarCenter.value;
    lidarWidthValue.textContent = lidarWidth.value;
    motorCenterValue.textContent = motorCenter.value;
    motorWidthValue.textContent = motorWidth.value;

    clearTimeout(sendTimer);
    sendTimer = setTimeout(sendConfig, 100);
  }

  [lidarCenter, lidarWidth, motorCenter, motorWidth].forEach((el) => {
    el.addEventListener('input', onSliderInput);
  });
  [lidarEnabled, motorEnabled].forEach((el) => {
    el.addEventListener('change', sendConfig);
  });

  context.onControlMessage((data) => {
    if (data.type !== 'audio_filter_config') return;
    applyConfigToControls(data);
  });

  context.sendControl({ type: 'get_audio_filter_config' });
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { pcmBase64ToFloat32, levelFromInt16, initMicTab, initMicFilterControls, initMicNoiseProfileControls, noiseProfileStatusLabel, MAX_SCHEDULE_DRIFT_SECONDS };
}
