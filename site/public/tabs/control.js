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

// Liczy PWM kół z ciągłego wektora ruchu (np. gałek pada): vy = przód/tył,
// vx = przesuw boczny, omega = obrót w miejscu, każdy w zakresie [-1, 1].
// Znaki poszczególnych składowych są brane wprost z DIRECTIONS, więc wynik
// pokrywa się z computeChannelValues dla wektorów jednostkowych (np. vy=1
// daje ten sam rezultat co aktywny kierunek 'Przód').
function computeChannelValuesFromVector(vy, vx, omega, maxPwm, motorPairs = DEFAULT_MOTOR_PAIRS) {
  const channelValues = {};
  for (let i = 0; i < 8; i++) {
    channelValues[i] = 0;
  }

  for (const role of WHEEL_ROLES) {
    const pair = motorPairs[role];
    if (!pair) continue;
    const [fCh, bCh] = pair;

    const vySign = DIRECTIONS['Przód'][role] || 0;
    const vxSign = DIRECTIONS['Full prawo'][role] || 0;
    const omegaSign = DIRECTIONS['Prawo'][role] || 0;

    const net = (vy * vySign + vx * vxSign + omega * omegaSign) * maxPwm;

    if (net > 0) {
      channelValues[fCh] = Math.round(Math.min(net, maxPwm));
      channelValues[bCh] = 0;
    } else if (net < 0) {
      channelValues[fCh] = 0;
      channelValues[bCh] = Math.round(Math.min(-net, maxPwm));
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
  const gamepadStatusEl = document.getElementById('gamepad-status');
  const modeRadios = document.querySelectorAll('input[name="control-mode"]');
  const deadzoneSlider = document.getElementById('gamepad-deadzone');

  let activeDanceTimer = null;
  let activeDanceName = null;
  let activeDanceLoop = false;

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
      activeDanceLoop = false;
      danceStatusEl.textContent = 'BRAK TAŃCA';
      danceStatusEl.className = 'status status-disconnected';
      setManualControlsEnabled(controlMode !== 'gamepad');
    }
  }

  function playDanceStep(dance, stepIndex) {
    if (stepIndex >= dance.steps.length) {
      if (activeDanceLoop) {
        playDanceStep(dance, 0);
        return;
      }
      stopDance();
      return;
    }
    const step = dance.steps[stepIndex];
    sendDirections(step.dirs, step.powerPct != null ? step.powerPct : dance.powerPct);
    activeDanceTimer = setTimeout(() => playDanceStep(dance, stepIndex + 1), step.ms);
  }

  function startDance(name, options = {}) {
    const dance = DANCES[name];
    if (!dance) return;
    stopDance();
    activeDanceName = name;
    activeDanceLoop = !!options.loop;
    danceStatusEl.textContent = `TANIEC: ${dance.label}`;
    danceStatusEl.className = 'status status-dancing';
    setManualControlsEnabled(false);
    playDanceStep(dance, 0);
  }

  danceButtons.forEach((btn) => {
    btn.addEventListener('click', () => startDance(btn.dataset.dance));
  });

  if (typeof window !== 'undefined') {
    window.robotDance = { start: startDance, stop: stopDance, DANCES };
  }

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

  slider.addEventListener('input', () => {
    updateAll();
    context.sendControl({ type: 'set_follow_band_speed', pwm: currentPwm() });
  });

  context.sendControl({ type: 'set_follow_band_speed', pwm: currentPwm() });

  // --- Sterowanie padem Bluetooth (Gamepad API) ---
  // Pad musi być już sparowany z systemem przez Bluetooth - przeglądarka
  // wykrywa go dopiero po naciśnięciu dowolnego przycisku na padzie.
  let controlMode = 'buttons';
  let connectedGamepadIndex = null;
  let gamepadLoopHandle = null;
  let lastSentVector = null;

  // Mapowanie przycisków ABXY (standardowy layout pada Xbox: 0=A, 1=B, 2=X, 3=Y)
  // na uruchamianie tańców, oraz stan wciśnięcia do wykrywania zbocza narastającego.
  const GAMEPAD_DANCE_BUTTONS = { 0: 'bujanie', 1: 'krok', 2: 'zygzak', 3: 'szal' };
  const gamepadButtonPressed = {};

  function deadzoneValue() {
    return Number(deadzoneSlider.value) / 100;
  }

  function applyDeadzone(value, deadzone) {
    if (Math.abs(value) < deadzone) return 0;
    return value;
  }

  function setControlMode(mode) {
    controlMode = mode;
    if (mode === 'gamepad') {
      setManualControlsEnabled(false);
    } else {
      setManualControlsEnabled(true);
      pressedButtons.clear();
      pressedKeys.clear();
      lastSentVector = null;
      sendDirections([], 0);
    }
  }

  modeRadios.forEach((radio) => {
    radio.addEventListener('change', () => {
      if (radio.checked) setControlMode(radio.value);
    });
  });

  function sendVector(vy, vx, omega, maxPwmOverride) {
    const maxPwm = maxPwmOverride != null ? maxPwmOverride : currentPwm();
    const values = computeChannelValuesFromVector(vy, vx, omega, maxPwm, motorPairs);
    const serialized = JSON.stringify(values);
    if (serialized === lastSentVector) return;
    lastSentVector = serialized;
    for (let channel = 0; channel < 8; channel++) {
      context.sendControl({ type: 'motor', channel, pwm: values[channel] });
    }
  }

  function padHasActivity(pad, deadzone) {
    if (!pad) return false;
    for (const btn of pad.buttons) {
      if (btn && (btn.pressed || btn.value > 0.5)) return true;
    }
    for (const axis of pad.axes) {
      if (Math.abs(axis) > deadzone) return true;
    }
    return false;
  }

  function switchToGamepadMode() {
    const gamepadRadio = document.querySelector('input[name="control-mode"][value="gamepad"]');
    if (gamepadRadio) gamepadRadio.checked = true;
    setControlMode('gamepad');
  }

  function pollGamepad() {
    gamepadLoopHandle = requestAnimationFrame(pollGamepad);
    if (connectedGamepadIndex === null) return;

    const pads = navigator.getGamepads ? navigator.getGamepads() : [];
    const pad = pads[connectedGamepadIndex];
    if (!pad) return;

    // Anty-debilne, ale ostrożne: nie przełączamy trybu samym faktem "podłączenia"
    // (niektóre urządzenia zgłaszają się w przeglądarce jako gamepad w spoczynku
    // i wcześniej to fałszywie przełączało tryb, blokując strzałki). Przełączamy
    // dopiero gdy ktoś faktycznie rusza gałką/wciska przycisk na padzie.
    if (controlMode !== 'gamepad') {
      if (padHasActivity(pad, deadzoneValue())) {
        switchToGamepadMode();
      } else {
        return;
      }
    }

    // ABXY -> tańce: wciśnięcie uruchamia taniec (wykrywane po zboczu narastającym,
    // żeby nie odpalać go ponownie co klatkę przy przytrzymanym przycisku).
    for (const [idx, danceName] of Object.entries(GAMEPAD_DANCE_BUTTONS)) {
      const btn = pad.buttons[idx];
      const pressed = !!(btn && btn.pressed);
      if (pressed && !gamepadButtonPressed[idx]) {
        startDance(danceName);
      }
      gamepadButtonPressed[idx] = pressed;
    }
    if (activeDanceName) return;

    // Lewa gałka (oś Y) = przód/tył, lewa gałka (oś X) = jazda bokiem,
    // prawa gałka (oś X) = obrót w miejscu.
    const deadzone = deadzoneValue();
    const leftY = applyDeadzone(pad.axes[1] || 0, deadzone);
    const leftX = applyDeadzone(pad.axes[0] || 0, deadzone);
    const rightX = applyDeadzone(pad.axes[2] || 0, deadzone);

    // Gałki zawsze sterują ruchem. RT (button 7) dokłada "boost" mocy ponad
    // suwak (do 100% zakresu PWM), LT (button 6) działa jak hamulec i
    // przycina moc maksymalną - żadne z nich nie jest wymagane do ruchu.
    const rtButton = pad.buttons[7];
    const ltButton = pad.buttons[6];
    const rtValue = rtButton ? rtButton.value : 0;
    const ltValue = ltButton ? ltButton.value : 0;

    const basePwm = currentPwm();
    const boostedPwm = basePwm + rtValue * (4095 - basePwm);
    const effectiveMaxPwm = Math.round(boostedPwm * (1 - ltValue * 0.9));

    // Oś Y gałki jest dodatnia w dół - odwracamy, by "do góry" = jazda do przodu.
    sendVector(-leftY, leftX, rightX, effectiveMaxPwm);
  }

  if (typeof requestAnimationFrame === 'function') {
    pollGamepad();
  }

  window.addEventListener('gamepadconnected', (event) => {
    connectedGamepadIndex = event.gamepad.index;
    gamepadStatusEl.textContent = `PODŁĄCZONO: ${event.gamepad.id}`;
    gamepadStatusEl.className = 'status status-connected';
  });

  window.addEventListener('gamepaddisconnected', (event) => {
    if (event.gamepad.index !== connectedGamepadIndex) return;
    connectedGamepadIndex = null;
    gamepadStatusEl.textContent = 'PAD NIEPODŁĄCZONY';
    gamepadStatusEl.className = 'status status-disconnected';
    if (controlMode === 'gamepad') {
      const buttonsRadio = document.querySelector('input[name="control-mode"][value="buttons"]');
      if (buttonsRadio) buttonsRadio.checked = true;
      setControlMode('buttons');
      lastSentVector = null;
      sendDirections([], 0);
    }
  });

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
  module.exports = { computeChannelValues, computeChannelValuesFromVector, recalcDirections, initControlTab, WHEEL_ROLES, DEFAULT_MOTOR_PAIRS, DANCES };
}
