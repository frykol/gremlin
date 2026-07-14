const DIRECTIONS = {
  'Przód': [0, 2, 5, 7],
  'Tył': [1, 3, 4, 6],
  'Prawo': [0, 2, 4, 6],
  'Lewo': [1, 3, 5, 7],
  'Full lewo': [1, 2, 5, 6],
  'Full prawo': [0, 3, 4, 7],
};

const MOTOR_PAIRS = [[0, 1], [2, 3], [5, 4], [7, 6]];

function computeChannelValues(activeDirections, pwmVal) {
  const channelValues = {};
  for (let i = 0; i < 8; i++) {
    channelValues[i] = 0;
  }

  for (const [fCh, bCh] of MOTOR_PAIRS) {
    let net = 0;
    for (const dir of activeDirections) {
      const chans = DIRECTIONS[dir] || [];
      if (chans.includes(fCh)) net += pwmVal;
      if (chans.includes(bCh)) net -= pwmVal;
    }
    if (net > 0) {
      channelValues[fCh] = Math.min(net, pwmVal);
      channelValues[bCh] = 0;
    } else if (net < 0) {
      channelValues[fCh] = 0;
      channelValues[bCh] = Math.min(Math.abs(net), pwmVal);
    } else {
      channelValues[fCh] = 0;
      channelValues[bCh] = 0;
    }
  }

  return channelValues;
}

function recalcDirections(pressedButtons, pressedKeys) {
  const dirs = new Set(pressedButtons);

  if (pressedKeys.has('Up')) dirs.add('Przód');
  if (pressedKeys.has('Down')) dirs.add('Tył');
  if (pressedKeys.has('Left')) {
    dirs.add(pressedKeys.has('Shift') ? 'Full lewo' : 'Lewo');
  }
  if (pressedKeys.has('Right')) {
    dirs.add(pressedKeys.has('Shift') ? 'Full prawo' : 'Prawo');
  }

  return dirs;
}

function initControlTab(context) {
  const statusEl = document.getElementById('control-status');
  const slider = document.getElementById('power-slider');
  const buttons = document.querySelectorAll('#tab-control [data-direction]');

  const pressedButtons = new Set();
  const pressedKeys = new Set();
  const keyReleaseTimers = {};
  let lastSent = null;

  function currentPwm() {
    return Math.round((Number(slider.value) / 100) * 4095);
  }

  function updateAll() {
    const activeDirections = recalcDirections(pressedButtons, pressedKeys);
    const pwmVal = currentPwm();
    const values = computeChannelValues(activeDirections, pwmVal);

    if (activeDirections.size === 0) {
      statusEl.textContent = 'NIEAKTYWNY';
      statusEl.className = 'status status-disconnected';
    } else {
      statusEl.textContent = `AKTYWNE: ${Array.from(activeDirections).join(',')}`;
      statusEl.className = 'status status-connected';
    }

    const serialized = JSON.stringify(values);
    if (serialized === lastSent) {
      return;
    }
    lastSent = serialized;

    for (let channel = 0; channel < 8; channel++) {
      context.sendControl({ type: 'motor', channel, pwm: values[channel] });
    }
  }

  buttons.forEach((btn) => {
    const direction = btn.dataset.direction;
    btn.addEventListener('mousedown', () => {
      pressedButtons.add(direction);
      updateAll();
    });
    btn.addEventListener('mouseup', () => {
      pressedButtons.delete(direction);
      updateAll();
    });
    btn.addEventListener('mouseleave', () => {
      pressedButtons.delete(direction);
      updateAll();
    });
  });

  slider.addEventListener('input', updateAll);

  const keyMap = { ArrowUp: 'Up', ArrowDown: 'Down', ArrowLeft: 'Left', ArrowRight: 'Right', Shift: 'Shift' };

  document.addEventListener('keydown', (event) => {
    const key = keyMap[event.key];
    if (!key) return;
    if (keyReleaseTimers[key]) {
      clearTimeout(keyReleaseTimers[key]);
      delete keyReleaseTimers[key];
    }
    if (!pressedKeys.has(key)) {
      pressedKeys.add(key);
      updateAll();
    }
  });

  document.addEventListener('keyup', (event) => {
    const key = keyMap[event.key];
    if (!key) return;
    if (keyReleaseTimers[key]) {
      clearTimeout(keyReleaseTimers[key]);
    }
    keyReleaseTimers[key] = setTimeout(() => {
      delete keyReleaseTimers[key];
      pressedKeys.delete(key);
      updateAll();
    }, 20);
  });
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { computeChannelValues, recalcDirections, initControlTab };
}
