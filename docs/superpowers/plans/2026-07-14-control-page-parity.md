# Control Page Feature Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port every tab of the old Tkinter desktop control app (Control/Camera/GPIO/I2C/Mic/Log + program ON/OFF) onto the browser control page (`site/public/`), reusing the WS message contract that's already wired end-to-end, plus one new `clear_logs` backend message.

**Architecture:** One HTML page with a sidebar of tab buttons; each tab is its own plain `<script>` file exposing pure, unit-testable logic functions (guarded with a CommonJS `module.exports` block so `node --test` can `require()` them) plus one `initXxxTab(context)` function that does DOM wiring, called by `app.js` after all tab scripts load. `app.js` owns the single control WebSocket and fans incoming JSON messages out to every tab via `context.onControlMessage(handler)`; tabs send commands via `context.sendControl(message)`.

**Tech Stack:** Same as the prior work — plain HTML/CSS/JS, no framework, no build step; Node's built-in `node --test` for JS logic tests; Python's `pytest` for the one backend change.

## Global Constraints

- No audio recording-to-file in the browser (Web Audio playback + level meter only — explicitly out of scope this iteration).
- No server-side camera rotation — rotation is a client-side CSS transform only; do not send any WS message for it (the old `{"type":"rotate"}` message is confirmed dead code server-side and is not being revived).
- No new build tooling or frontend framework.
- All existing WS message contracts (`gpio`, `motor`, `stream`, `audio_stream`, `set_program_status`, `get_program_status`, `{"send":"logs"}`, `register_video_sink`) must keep working unmodified — reuse them, don't change their shape.
- The only new backend message is `clear_logs`, handled directly in `main.py` (not routed to `CommandProcessor`/the child process), because `sim.log` is owned by `main.py` itself and clearing it must work whether or not `program_manager` is running.
- Node tests run via `node --test` from inside `site/`. Python tests run via `.venv/bin/python3 -m pytest <path> -v` from the repo root.
- Follow existing code style in each file; no comments except where non-obvious.

---

### Task 1: Backend `clear_logs` handling in `main.py`

**Files:**
- Modify: `src/main.py`
- Test: `tests/test_log_clearing.py` (new)

**Interfaces:**
- Produces: top-level function `_clear_log_file(log_file, path: str) -> TextIO` — closes the passed-in file handle, truncates the file at `path`, and returns a freshly-opened append-mode handle at the same path. Used by `main.py`'s `handle_instruction`.
- Consumes: nothing new.

- [ ] **Step 1: Write the failing test**

Create `tests/test_log_clearing.py`:

```python
import os

from src.main import _clear_log_file


def test_clear_log_file_truncates_and_reopens_for_append(tmp_path):
    log_path = tmp_path / "sim.log"
    log_path.write_text("old content\nmore old content\n", encoding="utf-8")

    handle = open(log_path, "a", encoding="utf-8")
    try:
        new_handle = _clear_log_file(handle, str(log_path))
        try:
            assert log_path.read_text(encoding="utf-8") == ""

            new_handle.write("fresh line\n")
            new_handle.flush()
            assert log_path.read_text(encoding="utf-8") == "fresh line\n"
        finally:
            new_handle.close()
    finally:
        if not handle.closed:
            handle.close()


def test_clear_log_file_handles_missing_file(tmp_path):
    log_path = tmp_path / "does_not_exist_yet.log"
    handle = open(log_path, "a", encoding="utf-8")

    new_handle = _clear_log_file(handle, str(log_path))
    try:
        assert os.path.exists(log_path)
        assert log_path.read_text(encoding="utf-8") == ""
    finally:
        new_handle.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_log_clearing.py -v`
Expected: FAIL with `ImportError: cannot import name '_clear_log_file' from 'src.main'`

- [ ] **Step 3: Write minimal implementation**

In `src/main.py`, add this top-level function after `_is_broken_pipe_error` (before `_write_instruction_to_child`):

```python
def _clear_log_file(log_file, path: str):
    try:
        log_file.close()
    except Exception:
        pass

    try:
        open(path, "w", encoding="utf-8").close()
    except Exception as e:
        print(f"Failed to clear log file: {e}")

    return open(path, "a", buffering=1, encoding="utf-8")
```

Then, inside `main()`'s `handle_instruction` function, add a new branch. Insert it right after the existing `if msg.get("type") == "set_program_status": ... return` block and before the `if msg.get("type") == "register_video_sink":` block:

```python
        if msg.get("type") == "clear_logs":
            nonlocal log_file
            log_file = _clear_log_file(log_file, SIM_LOG)
            try:
                await ws.send(json.dumps({"type": "clear_logs", "success": True}))
            except Exception as e:
                print(f"Failed to ack clear_logs: {e}")
            return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_log_clearing.py -v`
Expected: 2 passed

Then run the full suite to confirm nothing else broke from the `nonlocal log_file` addition:

Run: `.venv/bin/python3 -m pytest tests/ -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/main.py tests/test_log_clearing.py
git commit -m "feat: add clear_logs handling in main.py, extracted as testable helper"
```

---

### Task 2: Page shell — sidebar tabs, shared control context, program ON/OFF

This lays the foundation every other tab task depends on: the tab-switching UI, and `app.js`'s `context` object (`sendControl`/`onControlMessage`) that later tasks' `initXxxTab(context)` functions consume.

**Files:**
- Modify: `site/public/index.html` (full replacement)
- Modify: `site/public/app.js` (full replacement)
- Modify: `site/public/style.css` (additions)

**Interfaces:**
- Produces: `context.sendControl(message: object) -> void` (JSON-stringifies and sends over the control WS, no-ops if not open) and `context.onControlMessage(handler: (data: object) => void) -> void` (registers a handler called for every parsed incoming control-WS JSON message). Both are consumed by every `initXxxTab(context)` function in Tasks 3-8.
- Consumes: nothing new — reuses the existing `WebSocket('ws://'+ip+':8765')` control connection and `/api/config` + `/video` video-relay connection from the prior work.

- [ ] **Step 1: Replace `site/public/index.html`**

```html
<!doctype html>
<html lang="pl">
  <head>
    <meta charset="utf-8" />
    <title>Gremlin Control</title>
    <link rel="stylesheet" href="style.css" />
  </head>
  <body>
    <header>
      <h1>Gremlin Control</h1>

      <form id="connect-form">
        <label for="robot-ip">IP robota</label>
        <input id="robot-ip" name="robot-ip" type="text" placeholder="192.168.1.162" required />
        <button type="submit">Połącz</button>
      </form>

      <div id="status" class="status status-disconnected">Rozłączony</div>

      <div class="program-controls">
        <div id="program-status" class="status status-connecting">Program: ?</div>
        <button id="program-on">Program ON</button>
        <button id="program-off">Program OFF</button>
      </div>
    </header>

    <div class="layout">
      <nav class="sidebar">
        <button class="tab-button active" data-tab="control">Control</button>
        <button class="tab-button" data-tab="camera">Camera</button>
        <button class="tab-button" data-tab="gpio">GPIO</button>
        <button class="tab-button" data-tab="i2c">I2C</button>
        <button class="tab-button" data-tab="mic">Mikrofon</button>
        <button class="tab-button" data-tab="log">Log</button>
      </nav>

      <main>
        <section id="tab-control" class="tab-panel active">
          <div id="control-status" class="status status-disconnected">NIEAKTYWNY</div>
          <label for="power-slider">Moc silników (%)</label>
          <input id="power-slider" type="range" min="0" max="100" value="20" />
          <div class="control-grid">
            <button data-direction="Przód">Przód</button>
            <button data-direction="Lewo">Lewo</button>
            <button data-direction="Prawo">Prawo</button>
            <button data-direction="Full lewo">Full lewo</button>
            <button data-direction="Full prawo">Full prawo</button>
            <button data-direction="Tył">Tył</button>
          </div>
        </section>

        <section id="tab-camera" class="tab-panel">
          <img id="video" alt="Podgląd kamery" />
          <div class="camera-controls">
            <button id="camera-start">Start</button>
            <button id="camera-stop">Stop</button>
            <button id="camera-rotate">Obróć</button>
            <button id="camera-capture">Capture</button>
          </div>
        </section>

        <section id="tab-gpio" class="tab-panel">
          <div class="gpio-controls">
            <button id="gpio-set-0">0</button>
            <button id="gpio-set-1">1</button>
          </div>
          <div id="gpio-grid" class="gpio-grid"></div>
        </section>

        <section id="tab-i2c" class="tab-panel">
          <input id="i2c-slider" type="range" min="0" max="100" value="0" />
          <div id="i2c-buttons" class="i2c-grid"></div>
        </section>

        <section id="tab-mic" class="tab-panel">
          <div class="mic-controls">
            <button id="mic-start">Start</button>
            <button id="mic-stop">Stop</button>
            <label><input id="mic-playback" type="checkbox" checked /> Odsłuch</label>
          </div>
          <div id="mic-level" class="mic-level"><div id="mic-level-bar"></div></div>
          <div id="mic-level-text">0%</div>
        </section>

        <section id="tab-log" class="tab-panel">
          <button id="log-clear">Wyczyść Logi</button>
          <pre id="log-content"></pre>
        </section>
      </main>
    </div>

    <script src="tabs/control.js"></script>
    <script src="tabs/camera.js"></script>
    <script src="tabs/gpio.js"></script>
    <script src="tabs/i2c.js"></script>
    <script src="tabs/mic.js"></script>
    <script src="tabs/log.js"></script>
    <script src="app.js"></script>
  </body>
</html>
```

- [ ] **Step 2: Replace `site/public/app.js`**

```javascript
const form = document.getElementById('connect-form');
const ipInput = document.getElementById('robot-ip');
const statusEl = document.getElementById('status');
const videoEl = document.getElementById('video');
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
  typeof initI2cTab === 'function' ? initI2cTab : null,
  typeof initMicTab === 'function' ? initMicTab : null,
  typeof initLogTab === 'function' ? initLogTab : null,
];

for (const init of tabInitializers) {
  if (init) {
    init(context);
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
```

Note: `initXxxTab` functions don't exist yet (Tasks 3-8 create them) — the `typeof ... === 'function' ? ... : null` guards mean this file works correctly today even before those tabs exist, and each later task's tab becomes active without touching `app.js` again.

- [ ] **Step 3: Add sidebar/tab/program-controls styling to `site/public/style.css`**

Append to the end of the existing `site/public/style.css`:

```css
body {
  max-width: none;
}

header {
  max-width: 900px;
  margin: 0 auto;
}

.program-controls {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0.5rem 0;
}

.layout {
  display: flex;
  max-width: 900px;
  margin: 0 auto;
  gap: 1rem;
}

.sidebar {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 120px;
}

.tab-button {
  padding: 0.5rem;
  cursor: pointer;
  border: 1px solid #ccc;
  background: #f3f3f3;
  text-align: left;
}

.tab-button.active {
  background: #16a34a;
  color: #fff;
  font-weight: bold;
}

main {
  flex: 1;
}

.tab-panel {
  display: none;
}

.tab-panel.active {
  display: block;
}

.control-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.5rem;
  max-width: 400px;
  margin-top: 1rem;
}

.gpio-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.25rem;
  max-width: 300px;
  margin-top: 1rem;
}

.i2c-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.25rem;
  max-width: 400px;
  margin-top: 1rem;
}

.mic-level {
  width: 100%;
  max-width: 300px;
  height: 100px;
  background: #000;
  position: relative;
  margin-top: 1rem;
}

#mic-level-bar {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  background: #16a34a;
  height: 0%;
}

#log-content {
  background: #1e1e1e;
  color: #f1f1f1;
  padding: 1rem;
  max-height: 400px;
  overflow-y: auto;
  white-space: pre-wrap;
}

#log-content .log-error {
  color: #f44336;
}

#log-content .log-system {
  color: #2196f3;
}

#log-content .log-info {
  color: #4caf50;
}

#video.rotated {
  transform: rotate(180deg);
}
```

- [ ] **Step 4: Run the existing site test suite to confirm nothing regressed**

Run (from `site/`): `npm test`
Expected: all 4 existing tests still pass (this task doesn't touch `server.js`)

- [ ] **Step 5: Commit**

```bash
git add site/public/index.html site/public/app.js site/public/style.css
git commit -m "feat: add tab shell, shared control context, and program ON/OFF to control page"
```

---

### Task 3: Control tab (driving)

**Files:**
- Create: `site/public/tabs/control.js`
- Test: `site/tests/control-tab.test.js` (new)

**Interfaces:**
- Consumes: `context.sendControl`, `context.onControlMessage` (Task 2).
- Produces: `initControlTab(context)`, called by `app.js` (Task 2 already wires this in via `tabInitializers`). Exports `computeChannelValues`, `recalcDirections` as pure functions for testing.

- [ ] **Step 1: Write the failing test**

Create `site/tests/control-tab.test.js`:

```javascript
const test = require('node:test');
const assert = require('node:assert/strict');

const { computeChannelValues, recalcDirections } = require('../public/tabs/control.js');

test('computeChannelValues drives front-left/front-right channels forward for Przód', () => {
  const values = computeChannelValues(new Set(['Przód']), 100);
  assert.equal(values[0], 100);
  assert.equal(values[1], 0);
  assert.equal(values[2], 100);
  assert.equal(values[3], 0);
  assert.equal(values[5], 100);
  assert.equal(values[4], 0);
  assert.equal(values[7], 100);
  assert.equal(values[6], 0);
});

test('computeChannelValues drives reverse channels for Tył', () => {
  const values = computeChannelValues(new Set(['Tył']), 50);
  assert.equal(values[1], 50);
  assert.equal(values[0], 0);
  assert.equal(values[3], 50);
  assert.equal(values[2], 0);
});

test('computeChannelValues is all-zero with no active directions', () => {
  const values = computeChannelValues(new Set(), 100);
  for (let i = 0; i < 8; i++) {
    assert.equal(values[i], 0);
  }
});

test('recalcDirections maps arrow keys to direction names', () => {
  const dirs = recalcDirections(new Set(), new Set(['Up']));
  assert.ok(dirs.has('Przód'));
});

test('recalcDirections maps Shift+Left to Full lewo instead of Lewo', () => {
  const dirs = recalcDirections(new Set(), new Set(['Left', 'Shift']));
  assert.ok(dirs.has('Full lewo'));
  assert.ok(!dirs.has('Lewo'));
});

test('recalcDirections includes pressed buttons unchanged', () => {
  const dirs = recalcDirections(new Set(['Prawo']), new Set());
  assert.ok(dirs.has('Prawo'));
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `site/`): `npm test`
Expected: FAIL — `Cannot find module '../public/tabs/control.js'`

- [ ] **Step 3: Write minimal implementation**

Create `site/public/tabs/control.js`:

```javascript
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

    const serialized = JSON.stringify(values);
    if (serialized === lastSent) {
      return;
    }
    lastSent = serialized;

    if (activeDirections.size === 0) {
      statusEl.textContent = 'NIEAKTYWNY';
      statusEl.className = 'status status-disconnected';
    } else {
      statusEl.textContent = `AKTYWNE: ${Array.from(activeDirections).join(',')}`;
      statusEl.className = 'status status-connected';
    }

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
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `site/`): `npm test`
Expected: all tests pass (existing 4 + 6 new)

- [ ] **Step 5: Commit**

```bash
git add site/public/tabs/control.js site/tests/control-tab.test.js
git commit -m "feat: add Control tab (driving) to control page"
```

---

### Task 4: Camera tab (start/stop/rotate/capture)

**Files:**
- Create: `site/public/tabs/camera.js`
- Test: `site/tests/camera-tab.test.js` (new)

**Interfaces:**
- Consumes: `context.sendControl` (Task 2), the existing `<img id="video">` element (already present from the prior work, now inside `#tab-camera`).
- Produces: `initCameraTab(context)`. Exports `nextRotationClass` as a pure function.

- [ ] **Step 1: Write the failing test**

Create `site/tests/camera-tab.test.js`:

```javascript
const test = require('node:test');
const assert = require('node:assert/strict');

const { nextRotationClass } = require('../public/tabs/camera.js');

test('nextRotationClass toggles from empty to rotated', () => {
  assert.equal(nextRotationClass(''), 'rotated');
});

test('nextRotationClass toggles from rotated back to empty', () => {
  assert.equal(nextRotationClass('rotated'), '');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `site/`): `npm test`
Expected: FAIL — `Cannot find module '../public/tabs/camera.js'`

- [ ] **Step 3: Write minimal implementation**

Create `site/public/tabs/camera.js`:

```javascript
function nextRotationClass(current) {
  return current === 'rotated' ? '' : 'rotated';
}

function initCameraTab(context) {
  const videoEl = document.getElementById('video');
  const startBtn = document.getElementById('camera-start');
  const stopBtn = document.getElementById('camera-stop');
  const rotateBtn = document.getElementById('camera-rotate');
  const captureBtn = document.getElementById('camera-capture');

  startBtn.addEventListener('click', () => {
    context.sendControl({ type: 'stream', enabled: true });
  });

  stopBtn.addEventListener('click', () => {
    context.sendControl({ type: 'stream', enabled: false });
  });

  rotateBtn.addEventListener('click', () => {
    videoEl.className = nextRotationClass(videoEl.className);
  });

  captureBtn.addEventListener('click', () => {
    const canvas = document.createElement('canvas');
    canvas.width = videoEl.naturalWidth || videoEl.width;
    canvas.height = videoEl.naturalHeight || videoEl.height;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(videoEl, 0, 0);

    canvas.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `frame_${Date.now()}.jpg`;
      a.click();
      URL.revokeObjectURL(url);
    }, 'image/jpeg');
  });
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { nextRotationClass, initCameraTab };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `site/`): `npm test`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add site/public/tabs/camera.js site/tests/camera-tab.test.js
git commit -m "feat: add Camera tab controls (start/stop/rotate/capture) to control page"
```

---

### Task 5: GPIO tab

**Files:**
- Create: `site/public/tabs/gpio.js`
- Test: `site/tests/gpio-tab.test.js` (new)

**Interfaces:**
- Consumes: `context.sendControl` (Task 2).
- Produces: `initGpioTab(context)`. Exports `GPIO_PINS` for testing.

- [ ] **Step 1: Write the failing test**

Create `site/tests/gpio-tab.test.js`:

```javascript
const test = require('node:test');
const assert = require('node:assert/strict');

const { GPIO_PINS } = require('../public/tabs/gpio.js');

test('GPIO_PINS maps physical pin 7 to GPIO4', () => {
  assert.equal(GPIO_PINS[7], 'GPIO4');
});

test('GPIO_PINS maps physical pin 37 to GPIO26', () => {
  assert.equal(GPIO_PINS[37], 'GPIO26');
});

test('GPIO_PINS has exactly 13 mapped pins', () => {
  assert.equal(Object.keys(GPIO_PINS).length, 13);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `site/`): `npm test`
Expected: FAIL — `Cannot find module '../public/tabs/gpio.js'`

- [ ] **Step 3: Write minimal implementation**

Create `site/public/tabs/gpio.js`:

```javascript
const GPIO_PINS = {
  7: 'GPIO4',
  11: 'GPIO17',
  13: 'GPIO27',
  15: 'GPIO22',
  16: 'GPIO23',
  18: 'GPIO24',
  22: 'GPIO25',
  29: 'GPIO5',
  31: 'GPIO6',
  32: 'GPIO12',
  33: 'GPIO13',
  36: 'GPIO16',
  37: 'GPIO26',
};

function initGpioTab(context) {
  const grid = document.getElementById('gpio-grid');
  const set0Btn = document.getElementById('gpio-set-0');
  const set1Btn = document.getElementById('gpio-set-1');

  const buttons = {};
  const values = {};
  let activePin = null;

  for (let pin = 1; pin <= 40; pin++) {
    const label = GPIO_PINS[pin] || String(pin);
    const btn = document.createElement('button');
    btn.textContent = label;
    btn.disabled = !GPIO_PINS[pin];

    if (GPIO_PINS[pin]) {
      values[pin] = 0;
      btn.addEventListener('click', () => {
        activePin = pin;
        Object.values(buttons).forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
      });
    }

    buttons[pin] = btn;
    grid.appendChild(btn);
    updateButtonColor(pin);
  }

  function updateButtonColor(pin) {
    if (!GPIO_PINS[pin]) return;
    buttons[pin].style.background = values[pin] === 1 ? '#00ff00' : '#ff3333';
  }

  function setValue(value) {
    if (activePin === null) return;
    values[activePin] = value;
    updateButtonColor(activePin);
    context.sendControl({ type: 'gpio', pin_name: GPIO_PINS[activePin], value });
  }

  set0Btn.addEventListener('click', () => setValue(0));
  set1Btn.addEventListener('click', () => setValue(1));
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { GPIO_PINS, initGpioTab };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `site/`): `npm test`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add site/public/tabs/gpio.js site/tests/gpio-tab.test.js
git commit -m "feat: add GPIO tab to control page"
```

---

### Task 6: I2C tab

**Files:**
- Create: `site/public/tabs/i2c.js`
- Test: `site/tests/i2c-tab.test.js` (new)

**Interfaces:**
- Consumes: `context.sendControl` (Task 2).
- Produces: `initI2cTab(context)`. Exports `pwmFromPercent`, `oppositeChannel`, `I2C_LABELS` for testing.

- [ ] **Step 1: Write the failing test**

Create `site/tests/i2c-tab.test.js`:

```javascript
const test = require('node:test');
const assert = require('node:assert/strict');

const { pwmFromPercent, oppositeChannel, I2C_LABELS } = require('../public/tabs/i2c.js');

test('pwmFromPercent converts 0-100 range to 0-4095', () => {
  assert.equal(pwmFromPercent(0), 0);
  assert.equal(pwmFromPercent(100), 4095);
  assert.equal(pwmFromPercent(50), Math.round(50 * 40.95));
});

test('oppositeChannel pairs 0<->1, 2<->3, 4<->5, 6<->7', () => {
  assert.equal(oppositeChannel(0), 1);
  assert.equal(oppositeChannel(1), 0);
  assert.equal(oppositeChannel(6), 7);
  assert.equal(oppositeChannel(7), 6);
});

test('I2C_LABELS has 8 entries matching the old Tkinter labels', () => {
  assert.equal(I2C_LABELS.length, 8);
  assert.equal(I2C_LABELS[0], 'LP przód');
  assert.equal(I2C_LABELS[7], 'PT przód');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `site/`): `npm test`
Expected: FAIL — `Cannot find module '../public/tabs/i2c.js'`

- [ ] **Step 3: Write minimal implementation**

Create `site/public/tabs/i2c.js`:

```javascript
const I2C_LABELS = [
  'LP przód', 'LP tył',
  'LT przód', 'LT tył',
  'PP tył', 'PP przód',
  'PT tył', 'PT przód',
];

function pwmFromPercent(pct) {
  return Math.round(pct * 40.95);
}

function oppositeChannel(index) {
  return index ^ 1;
}

function initI2cTab(context) {
  const container = document.getElementById('i2c-buttons');
  const slider = document.getElementById('i2c-slider');

  const buttons = [];
  const values = new Array(8).fill(0);
  let activeIndex = 0;

  function sendMotor(channel, pwm) {
    context.sendControl({ type: 'motor', channel, pwm });
  }

  function updateButtonColor(index) {
    const v = values[index];
    const r = 255 - Math.round(v * 2.55);
    const g = Math.round(v * 2.55);
    buttons[index].style.background = `rgb(${r}, ${g}, 50)`;
  }

  I2C_LABELS.forEach((label, index) => {
    const btn = document.createElement('button');
    btn.textContent = label;
    btn.addEventListener('click', () => {
      activeIndex = index;
      buttons.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      slider.value = values[index];
    });
    buttons.push(btn);
    container.appendChild(btn);
    updateButtonColor(index);
  });

  slider.addEventListener('input', () => {
    const v = Number(slider.value);

    if (v > 0) {
      const opp = oppositeChannel(activeIndex);
      if (values[opp] > 0) {
        values[opp] = 0;
        updateButtonColor(opp);
        sendMotor(opp, 0);
      }
    }

    values[activeIndex] = v;
    updateButtonColor(activeIndex);
    sendMotor(activeIndex, pwmFromPercent(v));
  });
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { pwmFromPercent, oppositeChannel, I2C_LABELS, initI2cTab };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `site/`): `npm test`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add site/public/tabs/i2c.js site/tests/i2c-tab.test.js
git commit -m "feat: add I2C tab to control page"
```

---

### Task 7: Mic tab

**Files:**
- Create: `site/public/tabs/mic.js`
- Test: `site/tests/mic-tab.test.js` (new)

**Interfaces:**
- Consumes: `context.sendControl`, `context.onControlMessage` (Task 2). Reuses the existing `audio_chunk` message shape (`{"type":"audio_chunk","samples":"<base64>","timestamp":...,"sample_rate":...,"channels":1,"chunk_id":...,"source_channel":...}`) already sent by `AudioStreamer` — unchanged.
- Produces: `initMicTab(context)`. Exports `pcmBase64ToFloat32`, `levelFromInt16` for testing. Node 20 has global `atob`/`btoa`, so these are testable directly with `node --test` without a browser.

- [ ] **Step 1: Write the failing test**

Create `site/tests/mic-tab.test.js`:

```javascript
const test = require('node:test');
const assert = require('node:assert/strict');

const { pcmBase64ToFloat32, levelFromInt16 } = require('../public/tabs/mic.js');

function int16ArrayToBase64(int16) {
  const bytes = new Uint8Array(int16.buffer);
  let binary = '';
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary);
}

test('pcmBase64ToFloat32 decodes int16 PCM to normalized float32', () => {
  const int16 = new Int16Array([0, 16384, -32768, 32767]);
  const b64 = int16ArrayToBase64(int16);

  const float32 = pcmBase64ToFloat32(b64);

  assert.equal(float32.length, 4);
  assert.ok(Math.abs(float32[0] - 0) < 1e-6);
  assert.ok(Math.abs(float32[1] - 0.5) < 1e-3);
  assert.ok(Math.abs(float32[2] - -1) < 1e-3);
});

test('levelFromInt16 returns 0 for silence', () => {
  const int16 = new Int16Array([0, 0, 0]);
  assert.equal(levelFromInt16(int16), 0);
});

test('levelFromInt16 returns 100 for full-scale peak', () => {
  const int16 = new Int16Array([0, -32768, 100]);
  assert.equal(levelFromInt16(int16), 100);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `site/`): `npm test`
Expected: FAIL — `Cannot find module '../public/tabs/mic.js'`

- [ ] **Step 3: Write minimal implementation**

Create `site/public/tabs/mic.js`:

```javascript
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
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `site/`): `npm test`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add site/public/tabs/mic.js site/tests/mic-tab.test.js
git commit -m "feat: add Mic tab (level meter + Web Audio playback) to control page"
```

---

### Task 8: Log tab

**Files:**
- Create: `site/public/tabs/log.js`
- Test: `site/tests/log-tab.test.js` (new)

**Interfaces:**
- Consumes: `context.sendControl`, `context.onControlMessage` (Task 2). Reuses the existing `{"send":"logs"}` request / `{"type":"logs","file":"<base64>"}` response (already sent by `CommandProcessor._send_log`, unchanged). Sends the new `{"type":"clear_logs"}` message from Task 1 and expects `{"type":"clear_logs","success":true}` back.
- Produces: `initLogTab(context)`. Exports `classifyLogLine` for testing.

- [ ] **Step 1: Write the failing test**

Create `site/tests/log-tab.test.js`:

```javascript
const test = require('node:test');
const assert = require('node:assert/strict');

const { classifyLogLine } = require('../public/tabs/log.js');

test('classifyLogLine tags ERROR lines', () => {
  assert.equal(classifyLogLine('2026-07-14 ERROR something broke'), 'log-error');
});

test('classifyLogLine tags CRITICAL lines as error', () => {
  assert.equal(classifyLogLine('CRITICAL failure'), 'log-error');
});

test('classifyLogLine tags SYSTEM lines', () => {
  assert.equal(classifyLogLine('SYSTEM starting up'), 'log-system');
});

test('classifyLogLine tags INFO lines', () => {
  assert.equal(classifyLogLine('INFO all good'), 'log-info');
});

test('classifyLogLine returns null for unmatched lines', () => {
  assert.equal(classifyLogLine('just a plain line'), null);
});

test('classifyLogLine is case-insensitive', () => {
  assert.equal(classifyLogLine('error lowercase'), 'log-error');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `site/`): `npm test`
Expected: FAIL — `Cannot find module '../public/tabs/log.js'`

- [ ] **Step 3: Write minimal implementation**

Create `site/public/tabs/log.js`:

```javascript
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
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `site/`): `npm test`
Expected: all tests pass (existing tests from Tasks 3-7 plus these 6)

- [ ] **Step 5: Commit**

```bash
git add site/public/tabs/log.js site/tests/log-tab.test.js
git commit -m "feat: add Log tab (polling, tagging, clear) to control page"
```

---

### Task 9: End-to-end manual verification

No automated steps — requires the real Raspberry Pi and hardware (GPIO/I2C/camera/mic), same constraint as the prior WS-rewrite plan's Task 9. Do not claim this feature complete until these are actually run and observed.

- [ ] **Step 1: Run both full automated suites**

```bash
.venv/bin/python3 -m pytest tests/ -v
```
Expected: all passed

```bash
cd site && npm test
```
Expected: all passed

- [ ] **Step 2: Start the site and main.py, connect from a browser**

Follow the same startup steps as the prior plan's Task 9 (Steps 2-4): start `site/server.js`, start `python3 -m src.main` on the Pi, open the control page, enter the robot's IP, connect.

- [ ] **Step 3: Verify Program ON/OFF**

Click "Program ON" — status indicator should show "Program: ON" within ~1s (polled every 500ms). Click "Program OFF" — should revert. This replaces the old manual `wscat` workaround.

- [ ] **Step 4: Verify Control tab**

Press each direction button and each arrow key (with/without Shift) — confirm motors respond as expected and the status label reflects active directions. Verify the power slider changes the effective PWM magnitude.

- [ ] **Step 5: Verify Camera tab**

Start/stop the stream, confirm the image updates. Click "Obróć" — image should flip 180° instantly (client-side only, no network round-trip). Click "Capture" — a JPEG should download.

- [ ] **Step 6: Verify GPIO tab**

Select a mapped pin, set it to 1 then 0, confirm the physical pin toggles (measure with a multimeter or LED if available) and the button color reflects state.

- [ ] **Step 7: Verify I2C tab**

Select a channel, move the slider, confirm the corresponding motor channel responds. Verify that setting one channel of a pair (e.g. index 0) to nonzero while its pair (index 1) is nonzero correctly zeroes the pair first.

- [ ] **Step 8: Verify Mic tab**

Start the audio stream, confirm the level bar reacts to sound. With "Odsłuch" checked, confirm audio plays through the computer's speakers without audible gaps/stutter (Web Audio scheduling); uncheck it and confirm playback stops while the level meter keeps working.

- [ ] **Step 9: Verify Log tab**

Confirm the log content matches `sim.log` on the robot and updates roughly every 500ms. Trigger a few log lines with different keywords (or just observe existing INFO/ERROR lines) and confirm color-coding. Click "Wyczyść Logi" — confirm the displayed log clears and `sim.log` on the robot is actually truncated (check the file directly on the Pi).

- [ ] **Step 10: Record results**

If everything above matches, the feature is complete. If any step fails, treat it as a bug against this plan — do not mark the task done, and use `systematic-debugging` for that specific failure rather than patching around it here.
