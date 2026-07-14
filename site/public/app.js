const form = document.getElementById('connect-form');
const ipInput = document.getElementById('robot-ip');
const statusEl = document.getElementById('status');
const videoEl = document.getElementById('video');

let controlSocket = null;
let videoSocket = null;
let currentVideoUrl = null;

function setStatus(state) {
  const labels = {
    connecting: 'Łączenie...',
    connected: 'Połączony',
    disconnected: 'Rozłączony',
  };
  statusEl.textContent = labels[state] || labels.disconnected;
  statusEl.className = `status status-${state}`;
}

async function connectVideoRelay() {
  const response = await fetch('/api/config');
  const { udpPort } = await response.json();

  if (videoSocket) {
    videoSocket.close();
  }

  videoSocket = new WebSocket(`ws://${window.location.host}/video`);
  videoSocket.binaryType = 'arraybuffer';

  videoSocket.onmessage = (event) => {
    const blob = new Blob([event.data], { type: 'image/jpeg' });
    const url = URL.createObjectURL(blob);
    const previousUrl = currentVideoUrl;
    currentVideoUrl = url;
    videoEl.src = url;
    if (previousUrl) {
      URL.revokeObjectURL(previousUrl);
    }
  };

  return udpPort;
}

async function connect(robotIp) {
  setStatus('connecting');

  const udpPort = await connectVideoRelay();

  if (controlSocket) {
    controlSocket.close();
  }

  controlSocket = new WebSocket(`ws://${robotIp}:8765`);

  controlSocket.onopen = () => {
    setStatus('connected');
    controlSocket.send(JSON.stringify({
      type: 'register_video_sink',
      host: window.location.hostname,
      port: udpPort,
    }));
  };

  controlSocket.onclose = () => setStatus('disconnected');
  controlSocket.onerror = () => setStatus('disconnected');
}

form.addEventListener('submit', (event) => {
  event.preventDefault();
  connect(ipInput.value.trim());
});
