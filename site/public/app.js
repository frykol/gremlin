const form = document.getElementById('connect-form');
const ipInput = document.getElementById('robot-ip');
const statusEl = document.getElementById('status');
const videoEl = document.getElementById('video');
const videoPlaceholder = document.getElementById('video-placeholder');
const programStatusEl = document.getElementById('program-status');
const programOnBtn = document.getElementById('program-on');
const programOffBtn = document.getElementById('program-off');

let controlSocket = null;
let videoSocket = null;
let currentVideoUrl = null;
let programPollTimer = null;

const controlMessageHandlers = [];

function onControlMessage(handler) {
  controlMessageHandlers.push(handler);
}

function sendControl(message) {
  if (!controlSocket || controlSocket.readyState !== WebSocket.OPEN) {
    return;
  }
  controlSocket.send(JSON.stringify(message));
}

function setStatus(state) {
  const labels = {
    connecting: 'Łączenie...',
    connected: 'Połączony',
    disconnected: 'Rozłączony',
  };
  statusEl.textContent = labels[state] || labels.disconnected;
  statusEl.className = `status status-${state}`;
}

function setProgramStatus(status) {
  const labels = { on: 'Program: ON', off: 'Program: OFF', unknown: 'Program: ?' };
  const cssState = status === 'on' ? 'connected' : status === 'off' ? 'disconnected' : 'connecting';
  programStatusEl.textContent = labels[status] || labels.unknown;
  programStatusEl.className = `status status-${cssState}`;
}

function setVideoPlaceholderVisible(visible) {
  if (videoPlaceholder) {
    videoPlaceholder.style.display = visible ? 'flex' : 'none';
  }
}

onControlMessage((data) => {
  if (data.type === 'get_program_status' || data.type === 'program_status') {
    setProgramStatus(data.status);
  }
});

programOnBtn.addEventListener('click', () => {
  sendControl({ type: 'set_program_status', status: 'on' });
});

programOffBtn.addEventListener('click', () => {
  sendControl({ type: 'set_program_status', status: 'off' });
});

async function connectVideoRelay() {
  const response = await fetch('/api/config');
  const { udpPort } = await response.json();

  if (videoSocket) {
    videoSocket.close();
  }

  setVideoPlaceholderVisible(true);
  videoEl.src = '';

  videoSocket = new WebSocket(`ws://${window.location.host}/video`);
  videoSocket.binaryType = 'arraybuffer';

  videoSocket.onmessage = (event) => {
    const blob = new Blob([event.data], { type: 'image/jpeg' });
    const url = URL.createObjectURL(blob);
    const previousUrl = currentVideoUrl;
    currentVideoUrl = url;
    videoEl.src = url;
    setVideoPlaceholderVisible(false);
    if (previousUrl) {
      URL.revokeObjectURL(previousUrl);
    }
  };

  videoSocket.onerror = () => {
    setVideoPlaceholderVisible(true);
  };

  return udpPort;
}

async function connect(robotIp) {
  setStatus('connecting');

  const udpPort = await connectVideoRelay();

  if (controlSocket) {
    controlSocket.close();
  }
  if (programPollTimer) {
    clearInterval(programPollTimer);
    programPollTimer = null;
  }

  controlSocket = new WebSocket(`ws://${robotIp}:8765`);

  controlSocket.onopen = () => {
    setStatus('connected');
    sendControl({
      type: 'register_video_sink',
      host: window.location.hostname,
      port: udpPort,
    });
    programPollTimer = setInterval(() => {
      sendControl({ type: 'get_program_status' });
    }, 500);
  };

  controlSocket.onmessage = (event) => {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch (e) {
      return;
    }
    for (const handler of controlMessageHandlers) {
      handler(data);
    }
  };

  controlSocket.onclose = () => {
    setStatus('disconnected');
    setProgramStatus('unknown');
    if (programPollTimer) {
      clearInterval(programPollTimer);
      programPollTimer = null;
    }
  };
  controlSocket.onerror = () => setStatus('disconnected');
}

form.addEventListener('submit', (event) => {
  event.preventDefault();
  connect(ipInput.value.trim());
});

const context = { sendControl, onControlMessage };

const tabInitializers = [
  typeof initControlTab === 'function' ? initControlTab : null,
  typeof initCameraTab === 'function' ? initCameraTab : null,
  typeof initGpioTab === 'function' ? initGpioTab : null,
  typeof initEncodersTab === 'function' ? initEncodersTab : null,
  typeof initI2cTab === 'function' ? initI2cTab : null,
  typeof initAds1115Tab === 'function' ? initAds1115Tab : null,
  typeof initBandsTab === 'function' ? initBandsTab : null,
  typeof initColorDetectionTab === 'function' ? initColorDetectionTab : null,
  typeof initMicTab === 'function' ? initMicTab : null,
  typeof initVoiceTab === 'function' ? initVoiceTab : null,
  typeof initSpeakerTab === 'function' ? initSpeakerTab : null,
  typeof initLidarTab === 'function' ? initLidarTab : null,
  typeof initSystemStatusTab === 'function' ? initSystemStatusTab : null,
  typeof initLogTab === 'function' ? initLogTab : null,
  typeof initConfigTab === 'function' ? initConfigTab : null,
];

for (const init of tabInitializers) {
  if (init) {
    try {
      init(context);
    } catch (err) {
      // Jedna wadliwa zakladka nie moze ubijac inicjalizacji reszty -
      // bez tego np. blad w initSpeakerTab cichutko blokowal Lidar,
      // Log i Config (byly nizej na liscie).
      console.error('Blad inicjalizacji zakladki:', err);
    }
  }
}

document.querySelectorAll('.tab-button').forEach((btn) => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-panel').forEach((p) => p.classList.remove('active'));
    document.querySelectorAll('.tab-button').forEach((b) => b.classList.remove('active'));
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
    btn.classList.add('active');
  });
});
