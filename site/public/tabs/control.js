const WHEEL_ROLES = ['FL', 'FR', 'RL', 'RR'];

// Domyślne mapowanie roli koła -> [kanał_przód, kanał_tył] PWM.
// Rzeczywiste mapowanie pochodzi z config.json ("motors"), edytowalne w zakładce Config
// - to pozwala przypisać dowolny fizyczny silnik do dowolnej roli koła bez zmian w kodzie.
const DEFAULT_MOTOR_PAIRS = { FL: [0, 1], FR: [2, 3], RL: [5, 4], RR: [7, 6] };

// Znak (+1/-1/0) każdej roli koła dla danego kierunku jazdy (mecanum).
const DIRECTIONS = {
  'Przód': { FL: -1, FR: -1, RL: -1, RR: -1 },
  'Tył': { FL: 1, FR: 1, RL: 1, RR: 1 },
  'Prawo': { FL: 1, FR: -1, RL: 1, RR: -1 },
  'Lewo': { FL: -1, FR: 1, RL: -1, RR: 1 },
  'Full lewo': { FL: 1, FR: -1, RL: -1, RR: 1 },
  'Full prawo': { FL: -1, FR: 1, RL: 1, RR: -1 },
};

function computeChannelValues(activeDirections, pwmVal, motorPairs = DEFAULT_MOTOR_PAIRS) {
  const channelValues = {};
  for (let i = 0; i < 8; i++) {
    channelValues[i] = 0;
  }

  for (const role of WHEEL_ROLES) {
    const pair = motorPairs[role];
    if (!pair) continue;
    const [fCh, bCh] = pair;

    let net = 0;
    for (const dir of activeDirections) {
      const sign = (DIRECTIONS[dir] || {})[role] || 0;
      net += sign * pwmVal;
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

// Sekwencje tańców: lista kroków { dirs: [kierunki z DIRECTIONS], ms: czas trwania }.
const DANCES = {
  bujanie: {
    label: 'Bujanie',
    powerPct: 35,
    steps: [
      { dirs: ['Lewo'], ms: 350 },
      { dirs: ['Prawo'], ms: 350 },
      { dirs: ['Lewo'], ms: 350 },
      { dirs: ['Prawo'], ms: 350 },
      { dirs: ['Lewo'], ms: 350 },
      { dirs: ['Prawo'], ms: 350 },
    ],
  },
  krok: {
    label: 'Krok w bok',
    powerPct: 45,
    steps: [
      { dirs: ['Full lewo'], ms: 300 },
      { dirs: ['Full lewo'], ms: 300 },
      { dirs: [], ms: 150 },
      { dirs: ['Full prawo'], ms: 300 },
      { dirs: ['Full prawo'], ms: 300 },
      { dirs: [], ms: 150 },
      { dirs: ['Full lewo'], ms: 300 },
      { dirs: ['Full lewo'], ms: 300 },
      { dirs: [], ms: 150 },
      { dirs: ['Full prawo'], ms: 300 },
      { dirs: ['Full prawo'], ms: 300 },
    ],
  },
  zygzak: {
    label: 'Zygzak',
    powerPct: 40,
    steps: [
      { dirs: ['Przód', 'Lewo'], ms: 400 },
      { dirs: ['Tył', 'Prawo'], ms: 400 },
      { dirs: ['Przód', 'Prawo'], ms: 400 },
      { dirs: ['Tył', 'Lewo'], ms: 400 },
      { dirs: ['Przód', 'Lewo'], ms: 400 },
      { dirs: ['Tył', 'Prawo'], ms: 400 },
    ],
  },
  szal: {
    label: 'Szał',
    powerPct: 55,
    steps: [
      { dirs: ['Przód'], ms: 200 },
      { dirs: ['Full lewo'], ms: 200 },
      { dirs: ['Tył'], ms: 200 },
      { dirs: ['Full prawo'], ms: 200 },
      { dirs: ['Lewo'], ms: 200 },
      { dirs: ['Prawo'], ms: 200 },
      { dirs: ['Przód'], ms: 200 },
      { dirs: ['Tył'], ms: 200 },
    ],
  },
  spinjitsu: {
    label: 'Spinjitsu',
    powerPct: 10,
    // Obrót w miejscu (Prawo = przeciwne strony kręcą się przeciwnie) z mocą
    // rosnącą logarytmicznie od 8% do 65% (szybki przyrost na starcie,
    // spowalniający pod koniec) i dłuższym, 20-krokowym rozkręcaniem.
    steps: (() => {
      const stepCount = 20;
      const startPct = 8;
      const endPct = 65;
      const steps = [];
      for (let i = 0; i < stepCount; i++) {
        const t = i / (stepCount - 1);
        const logT = Math.log10(1 + 9 * t); // 0 -> 1, log-shaped
        const pct = Math.round(startPct + (endPct - startPct) * logT);
        steps.push({ dirs: ['Prawo'], ms: 350, powerPct: pct });
      }
      return steps;
    })(),
  },
};

function initControlTab(context) {
  const statusEl = document.getElementById('control-status');
  const slider = document.getElementById('power-slider');
  const buttons = document.querySelectorAll('#tab-control [data-direction]');
  const danceStatusEl = document.getElementById('dance-status');
  const danceButtons = document.querySelectorAll('#tab-control [data-dance]');
  const danceStopButton = document.getElementById('dance-stop');

  let activeDanceTimer = null;
  let activeDanceName = null;

  const pressedButtons = new Set();
  const pressedKeys = new Set();
  const keyReleaseTimers = {};
  let lastSent = null;
  let motorPairs = DEFAULT_MOTOR_PAIRS;

  fetch('/api/robot-config')
    .then((response) => (response.ok ? response.json() : null))
    .then((cfg) => {
      if (cfg && cfg.motors) {
        motorPairs = cfg.motors;
      }
    })
    .catch(() => {});

  function currentPwm() {
    return Math.round((Number(slider.value) / 100) * 4095);
  }

  function updateAll() {
    const activeDirections = recalcDirections(pressedButtons, pressedKeys);
    const pwmVal = currentPwm();
    const values = computeChannelValues(activeDirections, pwmVal, motorPairs);

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

  function sendDirections(dirs, powerPct) {
    const pwmVal = Math.round((powerPct / 100) * 4095);
    const values = computeChannelValues(new Set(dirs), pwmVal, motorPairs);
    for (let channel = 0; channel < 8; channel++) {
      context.sendControl({ type: 'motor', channel, pwm: values[channel] });
    }
  }

  function setManualControlsEnabled(enabled) {
    buttons.forEach((btn) => { btn.disabled = !enabled; });
    slider.disabled = !enabled;
  }

  function stopDance() {
    if (activeDanceTimer) {
      clearTimeout(activeDanceTimer);
      activeDanceTimer = null;
    }
    if (activeDanceName) {
      sendDirections([], 0);
      activeDanceName = null;
      danceStatusEl.textContent = 'BRAK TAŃCA';
      danceStatusEl.className = 'status status-disconnected';
      setManualControlsEnabled(true);
    }
  }

  function playDanceStep(dance, stepIndex) {
    if (stepIndex >= dance.steps.length) {
      stopDance();
      return;
    }
    const step = dance.steps[stepIndex];
    sendDirections(step.dirs, step.powerPct != null ? step.powerPct : dance.powerPct);
    activeDanceTimer = setTimeout(() => playDanceStep(dance, stepIndex + 1), step.ms);
  }

  function startDance(name) {
    const dance = DANCES[name];
    if (!dance) return;
    stopDance();
    activeDanceName = name;
    danceStatusEl.textContent = `TANIEC: ${dance.label}`;
    danceStatusEl.className = 'status status-dancing';
    setManualControlsEnabled(false);
    playDanceStep(dance, 0);
  }

  danceButtons.forEach((btn) => {
    btn.addEventListener('click', () => startDance(btn.dataset.dance));
  });

  if (danceStopButton) {
    danceStopButton.addEventListener('click', stopDance);
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

  const controlTabButton = document.querySelector('.tab-button[data-tab="control"]');
  if (controlTabButton) {
    controlTabButton.addEventListener('click', () => {
      lastSent = null;
    });
  }

  function isControlInputAllowed() {
    const controlPanel = document.getElementById('tab-control');
    if (!controlPanel || !controlPanel.classList.contains('active')) return false;
    const tag = document.activeElement && document.activeElement.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA') return false;
    if (document.activeElement && document.activeElement.isContentEditable) return false;
    return true;
  }

  const keyMap = { ArrowUp: 'Up', ArrowDown: 'Down', ArrowLeft: 'Left', ArrowRight: 'Right', Shift: 'Shift' };

  document.addEventListener('keydown', (event) => {
    if (!isControlInputAllowed()) return;
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
  module.exports = { computeChannelValues, recalcDirections, initControlTab, WHEEL_ROLES, DEFAULT_MOTOR_PAIRS, DANCES };
}
