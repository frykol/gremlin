function classifyLogLine(line) {
  const upper = line.toUpperCase();
  if (upper.includes('ERROR') || upper.includes('CRITICAL')) return 'log-error';
  if (upper.includes('SYSTEM')) return 'log-system';
  if (upper.includes('INFO')) return 'log-info';
  return null;
}

function initLogTab(context) {
  const contentEl = document.getElementById('log-content');
  const clearBtn = document.getElementById('log-clear');

  let lastContent = null;
  let pollTimer = null;

  function render(content) {
    if (content === lastContent) return;
    lastContent = content;

    contentEl.textContent = '';
    for (const line of content.split('\n')) {
      const span = document.createElement('span');
      const cls = classifyLogLine(line);
      if (cls) span.className = cls;
      span.textContent = `${line}\n`;
      contentEl.appendChild(span);
    }
  }

  context.onControlMessage((data) => {
    if (data.type === 'logs' && typeof data.file === 'string') {
      const content = atob(data.file);
      render(content);
    }
  });

  clearBtn.addEventListener('click', () => {
    context.sendControl({ type: 'clear_logs' });
  });

  if (pollTimer) {
    clearInterval(pollTimer);
  }
  pollTimer = setInterval(() => {
    context.sendControl({ send: 'logs' });
  }, 500);
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { classifyLogLine, initLogTab };
}
