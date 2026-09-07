const SYSTEM_STATUS_DEVICES = ['OAK-D', 'LIDAR', 'MIC', 'SPEAKER', 'ADS1115', 'I2C', 'SD-CARD'];

function classifySystemStatus(status) {
  if (status.includes('FALLBACK')) return 'system-status-fallback';
  if (status.includes('ERROR')) return 'system-status-error';
  if (status.includes('DUMMY')) return 'system-status-dummy';
  if (status.includes('SUCCESS')) return 'system-status-success';
  return 'system-status-unknown';
}

function parseSystemStatusLog(content) {
  const latest = {};
  for (const line of content.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const spaceIndex = trimmed.indexOf(' ');
    if (spaceIndex === -1) continue;
    const device = trimmed.slice(0, spaceIndex);
    const status = trimmed.slice(spaceIndex + 1);
    latest[device] = status;
  }
  return latest;
}

function initSystemStatusTab(context) {
  const gridEl = document.getElementById('system-status-grid');
  if (!gridEl) return;

  const cards = new Map();
  for (const device of SYSTEM_STATUS_DEVICES) {
    const card = document.createElement('div');
    card.className = 'system-status-card';

    const name = document.createElement('div');
    name.className = 'system-status-name';
    name.textContent = device;

    const badge = document.createElement('div');
    badge.className = 'system-status-badge system-status-unknown';
    badge.textContent = 'BRAK DANYCH';

    card.appendChild(name);
    card.appendChild(badge);
    gridEl.appendChild(card);
    cards.set(device, badge);
  }

  let lastContent = null;

  function render(content) {
    if (content === lastContent) return;
    lastContent = content;

    const latest = parseSystemStatusLog(content);
    for (const [device, badge] of cards) {
      const status = latest[device];
      if (!status) {
        badge.className = 'system-status-badge system-status-unknown';
        badge.textContent = 'BRAK DANYCH';
        continue;
      }
      badge.className = `system-status-badge ${classifySystemStatus(status)}`;
      badge.textContent = status;
    }
  }

  context.onControlMessage((data) => {
    if (data.type === 'status' && typeof data.file === 'string') {
      const content = atob(data.file);
      render(content);
    }
  });

  setInterval(() => {
    context.sendControl({ send: 'status' });
  }, 500);
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { classifySystemStatus, parseSystemStatusLog, initSystemStatusTab, SYSTEM_STATUS_DEVICES };
}
