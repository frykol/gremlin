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
    return audioCtx;
  }

  function playChunk(float32, rate) {
    if (!playbackCheckbox.checked) return;
    const ctx = ensureAudioContext(rate);
    const buffer = ctx.createBuffer(1, float32.length, rate);
    buffer.copyToChannel(float32, 0);

    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);

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
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { pcmBase64ToFloat32, levelFromInt16, initMicTab };
}
