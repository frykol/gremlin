function formatVoiceTime(epochSeconds) {
  if (!epochSeconds) return '';
  const date = new Date(epochSeconds * 1000);
  return date.toLocaleTimeString();
}

function initVoiceTab(context) {
  const lastTextEl = document.getElementById('voice-last-text');
  const lastActionEl = document.getElementById('voice-last-action');
  const historyEl = document.getElementById('voice-history');
  if (!lastTextEl) return;

  context.onControlMessage((data) => {
    if (data.type !== 'voice_recognition_state') return;

    lastTextEl.textContent = data.last_text || '—';
    lastActionEl.textContent = data.last_action || '—';

    if (historyEl) {
      historyEl.innerHTML = '';
      const history = data.history || [];
      for (let i = history.length - 1; i >= 0; i--) {
        const entry = history[i];
        const li = document.createElement('li');
        const time = formatVoiceTime(entry.time);
        li.textContent = entry.action
          ? `[${time}] "${entry.text}" → ${entry.action}`
          : `[${time}] "${entry.text}"`;
        historyEl.appendChild(li);
      }
    }
  });

  setInterval(() => {
    context.sendControl({ type: 'get_voice_recognition_state' });
  }, 500);
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { formatVoiceTime, initVoiceTab };
}
