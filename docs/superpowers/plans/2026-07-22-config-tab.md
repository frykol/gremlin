# Config Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Config" tab to the `site` control panel that lets a user view and edit every value in the repo-root `config.json` (without adding/removing keys) and save it back to disk before starting the main program.

**Architecture:** Two new Express routes in `site/server.js` (`GET`/`PUT /api/robot-config`) read/write the JSON file directly. A new client module `site/public/tabs/config.js` recursively renders the fetched JSON into a form (objects → grouped fields, arrays → fixed-length rows, booleans → checkboxes, numbers/strings → inputs), tracks edits in an in-memory clone, and PUTs the whole object back on "Zapisz". Wired into `index.html` and `app.js` following the existing tab pattern (see `site/public/tabs/encoders.js`, `site/public/tabs/log.js`).

**Tech Stack:** Node.js, Express 4, `node --test` (existing test runner, no new dependencies), vanilla JS/DOM (no framework), existing `site/public/style.css`.

## Global Constraints

- No new npm dependencies — reuse `express` (already a dependency) and Node's built-in `fs`.
- Tests use `node --test` via `npm test` (`site/package.json:8`), matching the style of `site/tests/config_endpoint.test.js` and `site/tests/log-tab.test.js`.
- Client tab modules must export via `if (typeof module !== 'undefined' && module.exports) { module.exports = {...} }` so `node --test` can `require()` them directly (see `site/public/tabs/encoders.js:47-49`).
- Tab UI must not allow adding or removing keys/array elements — only editing existing scalar values (explicit spec requirement).
- `createApp` must accept a `configPath` override so tests never touch the real repo `config.json` (spec requirement, keeps tests hermetic).

---

## File Structure

- **Modify `site/server.js`** — add `express.json()` middleware, add `configPath` option to `createApp`, add `GET /api/robot-config` and `PUT /api/robot-config` routes.
- **Modify `site/tests/config_endpoint.test.js`** — add test cases for the two new routes.
- **Create `site/public/tabs/config.js`** — `buildFormTree`, `applyEdit`, `initConfigTab`, DOM rendering.
- **Create `site/tests/config-tab.test.js`** — unit tests for `buildFormTree` and `applyEdit`.
- **Modify `site/public/index.html`** — sidebar button, tab panel markup, script tag.
- **Modify `site/public/app.js`** — register `initConfigTab` in `tabInitializers`.
- **Modify `site/public/style.css`** — minimal styles for the generated form (field groups, rows, status message), following existing class-naming conventions (e.g. `.panel-card`, `.encoder-card`).

---

### Task 1: Server routes for reading and writing config.json

**Files:**
- Modify: `site/server.js`
- Test: `site/tests/config_endpoint.test.js`

**Interfaces:**
- Produces: `createApp({ udpPort, configPath })` — `configPath` defaults to `path.join(__dirname, '..', 'config.json')`. Routes `GET /api/robot-config` (200 parsed JSON object, 404 `{ error }` if file missing, 500 `{ error }` if unparseable) and `PUT /api/robot-config` (200 `{ success: true }` on valid object body written to `configPath`; 400 `{ error }` if body is missing/not a plain object/is an array; 500 `{ error }` if the write fails).

- [ ] **Step 1: Write the failing tests**

Add to `site/tests/config_endpoint.test.js` (append after the existing test, adding `fs`/`os` requires at top):

```javascript
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { createApp } = require('../server');

test('GET /api/config returns the configured UDP port', async () => {
  const app = createApp({ udpPort: 9123 });
  const server = http.createServer(app);

  await new Promise((resolve) => server.listen(0, resolve));
  const { port } = server.address();

  const body = await new Promise((resolve, reject) => {
    http.get(`http://127.0.0.1:${port}/api/config`, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => resolve(data));
    }).on('error', reject);
  });

  assert.deepEqual(JSON.parse(body), { udpPort: 9123 });

  await new Promise((resolve) => server.close(resolve));
});

function makeTempConfigPath(name) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'gremlin-config-test-'));
  return path.join(dir, name);
}

function httpRequest(port, method, urlPath, body) {
  return new Promise((resolve, reject) => {
    const data = body === undefined ? null : JSON.stringify(body);
    const req = http.request(
      {
        host: '127.0.0.1',
        port,
        path: urlPath,
        method,
        headers: data ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } : {},
      },
      (res) => {
        let chunks = '';
        res.on('data', (chunk) => { chunks += chunk; });
        res.on('end', () => resolve({ status: res.statusCode, body: chunks }));
      }
    );
    req.on('error', reject);
    if (data) req.write(data);
    req.end();
  });
}

test('GET /api/robot-config returns the parsed config file', async () => {
  const configPath = makeTempConfigPath('config.json');
  fs.writeFileSync(configPath, JSON.stringify({ dev: true, gpio: { chip: '/dev/gpiochip0' } }));

  const app = createApp({ udpPort: 9000, configPath });
  const server = http.createServer(app);
  await new Promise((resolve) => server.listen(0, resolve));
  const { port } = server.address();

  const { status, body } = await httpRequest(port, 'GET', '/api/robot-config');

  assert.equal(status, 200);
  assert.deepEqual(JSON.parse(body), { dev: true, gpio: { chip: '/dev/gpiochip0' } });

  await new Promise((resolve) => server.close(resolve));
});

test('GET /api/robot-config returns 404 when the file is missing', async () => {
  const configPath = makeTempConfigPath('missing-config.json');

  const app = createApp({ udpPort: 9000, configPath });
  const server = http.createServer(app);
  await new Promise((resolve) => server.listen(0, resolve));
  const { port } = server.address();

  const { status, body } = await httpRequest(port, 'GET', '/api/robot-config');

  assert.equal(status, 404);
  assert.ok(JSON.parse(body).error);

  await new Promise((resolve) => server.close(resolve));
});

test('GET /api/robot-config returns 500 when the file has invalid JSON', async () => {
  const configPath = makeTempConfigPath('bad-config.json');
  fs.writeFileSync(configPath, '{ not valid json');

  const app = createApp({ udpPort: 9000, configPath });
  const server = http.createServer(app);
  await new Promise((resolve) => server.listen(0, resolve));
  const { port } = server.address();

  const { status, body } = await httpRequest(port, 'GET', '/api/robot-config');

  assert.equal(status, 500);
  assert.ok(JSON.parse(body).error);

  await new Promise((resolve) => server.close(resolve));
});

test('PUT /api/robot-config writes the body to disk and returns success', async () => {
  const configPath = makeTempConfigPath('config.json');
  fs.writeFileSync(configPath, JSON.stringify({ dev: true }));

  const app = createApp({ udpPort: 9000, configPath });
  const server = http.createServer(app);
  await new Promise((resolve) => server.listen(0, resolve));
  const { port } = server.address();

  const { status, body } = await httpRequest(port, 'PUT', '/api/robot-config', { dev: false, gpio: { chip: '/dev/gpiochip1' } });

  assert.equal(status, 200);
  assert.deepEqual(JSON.parse(body), { success: true });
  assert.deepEqual(JSON.parse(fs.readFileSync(configPath, 'utf8')), { dev: false, gpio: { chip: '/dev/gpiochip1' } });

  await new Promise((resolve) => server.close(resolve));
});

test('PUT /api/robot-config returns 400 for a non-object body', async () => {
  const configPath = makeTempConfigPath('config.json');
  fs.writeFileSync(configPath, JSON.stringify({ dev: true }));

  const app = createApp({ udpPort: 9000, configPath });
  const server = http.createServer(app);
  await new Promise((resolve) => server.listen(0, resolve));
  const { port } = server.address();

  const { status, body } = await httpRequest(port, 'PUT', '/api/robot-config', [1, 2, 3]);

  assert.equal(status, 400);
  assert.ok(JSON.parse(body).error);
  assert.deepEqual(JSON.parse(fs.readFileSync(configPath, 'utf8')), { dev: true });

  await new Promise((resolve) => server.close(resolve));
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd site && npm test`
Expected: FAIL — `GET /api/robot-config` / `PUT /api/robot-config` return 404 (route doesn't exist) or similar errors, since the routes and `configPath` option don't exist yet.

- [ ] **Step 3: Implement the routes**

Replace the top of `site/server.js` (imports and `createApp`) with:

```javascript
const express = require('express');
const path = require('path');
const fs = require('fs');
const dgram = require('dgram');
const { WebSocketServer } = require('ws');

function createApp(options = {}) {
  const udpPort = options.udpPort || Number(process.env.UDP_PORT) || 9000;
  const configPath = options.configPath || path.join(__dirname, '..', 'config.json');

  const app = express();
  app.use(express.json());
  app.use(express.static(path.join(__dirname, 'public')));
  app.get('/api/config', (req, res) => {
    res.json({ udpPort });
  });

  app.get('/api/robot-config', (req, res) => {
    let raw;
    try {
      raw = fs.readFileSync(configPath, 'utf8');
    } catch (e) {
      res.status(404).json({ error: `Config file not found: ${e.message}` });
      return;
    }

    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (e) {
      res.status(500).json({ error: `Config file is not valid JSON: ${e.message}` });
      return;
    }

    res.json(parsed);
  });

  app.put('/api/robot-config', (req, res) => {
    const body = req.body;
    const isPlainObject = body !== null && typeof body === 'object' && !Array.isArray(body);
    if (!isPlainObject) {
      res.status(400).json({ error: 'Request body must be a JSON object' });
      return;
    }

    try {
      fs.writeFileSync(configPath, JSON.stringify(body, null, 2) + '\n');
    } catch (e) {
      res.status(500).json({ error: `Failed to write config file: ${e.message}` });
      return;
    }

    res.json({ success: true });
  });

  return app;
}
```

Leave the rest of `site/server.js` (`createVideoRelay`, `module.exports`, the `require.main === module` block) unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd site && npm test`
Expected: PASS for all tests in `config_endpoint.test.js`.

- [ ] **Step 5: Commit**

```bash
git add site/server.js site/tests/config_endpoint.test.js
git commit -m "feat: add GET/PUT /api/robot-config endpoints to site server"
```

---

### Task 2: Client-side form builder and edit logic (pure functions, unit tested)

**Files:**
- Create: `site/public/tabs/config.js`
- Test: `site/tests/config-tab.test.js`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `buildFormTree(value, path = [])` → returns a plain-object tree description (defined below) used by `initConfigTab`'s DOM rendering in Task 3. `applyEdit(root, path, rawValue)` → returns a new cloned object with the value at `path` overwritten. `initConfigTab(context)` (DOM-dependent, exercised in Task 3/manual testing, not unit tested here — the exports exist so Task 3 can build on them, but this task only tests the two pure functions).

`buildFormTree` node shape (one node per leaf or group):

```javascript
// leaf node
{ kind: 'leaf', path: ['gpio', 'chip'], type: 'string', value: '/dev/gpiochip0' }
// group node (object)
{ kind: 'group', path: ['gpio'], key: 'gpio', children: [ /* nested nodes */ ] }
// row node (array) — children are leaves only, one per element, type inferred per-element
{ kind: 'row', path: ['gpio', 'encoders', 'FL'], key: 'FL', children: [ /* leaf nodes, index-labeled */ ] }
```

Leaf `type` is one of `'boolean' | 'number' | 'string' | 'json'` (`'json'` is the fallback for anything else, e.g. `null`, holding `JSON.stringify(value)` as its `value`).

- [ ] **Step 1: Write the failing tests**

Create `site/tests/config-tab.test.js`:

```javascript
const test = require('node:test');
const assert = require('node:assert/strict');

const { buildFormTree, applyEdit } = require('../public/tabs/config');

test('buildFormTree builds a leaf node for a top-level boolean', () => {
  const tree = buildFormTree({ dev: true });
  assert.deepEqual(tree, {
    kind: 'group',
    path: [],
    key: null,
    children: [
      { kind: 'leaf', path: ['dev'], type: 'boolean', value: true },
    ],
  });
});

test('buildFormTree builds nested groups for nested objects', () => {
  const tree = buildFormTree({ gpio: { chip: '/dev/gpiochip0' } });
  assert.deepEqual(tree, {
    kind: 'group',
    path: [],
    key: null,
    children: [
      {
        kind: 'group',
        path: ['gpio'],
        key: 'gpio',
        children: [
          { kind: 'leaf', path: ['gpio', 'chip'], type: 'string', value: '/dev/gpiochip0' },
        ],
      },
    ],
  });
});

test('buildFormTree builds a row of leaves for an array of numbers', () => {
  const tree = buildFormTree({ encoders: { FL: [17, 27] } });
  const gpioGroup = tree.children[0];
  const row = gpioGroup.children[0];
  assert.deepEqual(row, {
    kind: 'row',
    path: ['encoders', 'FL'],
    key: 'FL',
    children: [
      { kind: 'leaf', path: ['encoders', 'FL', 0], type: 'number', value: 17 },
      { kind: 'leaf', path: ['encoders', 'FL', 1], type: 'number', value: 27 },
    ],
  });
});

test('buildFormTree falls back to json type for null', () => {
  const tree = buildFormTree({ nothing: null });
  assert.deepEqual(tree.children[0], { kind: 'leaf', path: ['nothing'], type: 'json', value: 'null' });
});

test('applyEdit overwrites a top-level scalar without touching siblings', () => {
  const root = { dev: true, is_custom: false };
  const result = applyEdit(root, ['dev'], false);
  assert.deepEqual(result, { dev: false, is_custom: false });
  assert.equal(root.dev, true, 'original object must not be mutated');
});

test('applyEdit overwrites a nested value', () => {
  const root = { gpio: { chip: '/dev/gpiochip0', pins: {} } };
  const result = applyEdit(root, ['gpio', 'chip'], '/dev/gpiochip1');
  assert.deepEqual(result, { gpio: { chip: '/dev/gpiochip1', pins: {} } });
});

test('applyEdit overwrites an array element by index', () => {
  const root = { encoders: { FL: [17, 27] } };
  const result = applyEdit(root, ['encoders', 'FL', 1], 99);
  assert.deepEqual(result, { encoders: { FL: [17, 99] } });
});

test('applyEdit never adds new keys', () => {
  const root = { dev: true };
  const result = applyEdit(root, ['dev'], false);
  assert.deepEqual(Object.keys(result), Object.keys(root));
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd site && npm test`
Expected: FAIL — `Cannot find module '../public/tabs/config'`.

- [ ] **Step 3: Implement `buildFormTree` and `applyEdit`**

Create `site/public/tabs/config.js`:

```javascript
function leafType(value) {
  if (typeof value === 'boolean') return 'boolean';
  if (typeof value === 'number') return 'number';
  if (typeof value === 'string') return 'string';
  return 'json';
}

function leafValue(value, type) {
  return type === 'json' ? JSON.stringify(value) : value;
}

function buildFormTree(value, path = [], key = null) {
  if (Array.isArray(value)) {
    return {
      kind: 'row',
      path,
      key,
      children: value.map((item, index) => {
        const itemPath = path.concat(index);
        const type = leafType(item);
        return { kind: 'leaf', path: itemPath, type, value: leafValue(item, type) };
      }),
    };
  }

  if (value !== null && typeof value === 'object') {
    return {
      kind: 'group',
      path,
      key,
      children: Object.keys(value).map((childKey) => {
        const childPath = path.concat(childKey);
        return buildFormTree(value[childKey], childPath, childKey);
      }),
    };
  }

  const type = leafType(value);
  return { kind: 'leaf', path, type, value: leafValue(value, type) };
}

function cloneDeep(value) {
  if (Array.isArray(value)) return value.map(cloneDeep);
  if (value !== null && typeof value === 'object') {
    const out = {};
    for (const k of Object.keys(value)) out[k] = cloneDeep(value[k]);
    return out;
  }
  return value;
}

function applyEdit(root, path, rawValue) {
  const clone = cloneDeep(root);
  let node = clone;
  for (let i = 0; i < path.length - 1; i += 1) {
    node = node[path[i]];
  }
  node[path[path.length - 1]] = rawValue;
  return clone;
}

function initConfigTab(context) {
  const formEl = document.getElementById('config-form');
  const saveBtn = document.getElementById('config-save');
  const statusEl = document.getElementById('config-status');

  let working = null;

  function setStatus(message, isError) {
    if (!statusEl) return;
    statusEl.textContent = message;
    statusEl.className = isError ? 'config-status config-status-error' : 'config-status config-status-ok';
  }

  function renderNode(node, container) {
    if (node.kind === 'group') {
      const group = document.createElement('fieldset');
      group.className = 'config-group';
      if (node.key) {
        const legend = document.createElement('legend');
        legend.textContent = node.key;
        group.appendChild(legend);
      }
      for (const child of node.children) {
        renderNode(child, group);
      }
      container.appendChild(group);
      return;
    }

    if (node.kind === 'row') {
      const row = document.createElement('div');
      row.className = 'config-row';
      const label = document.createElement('span');
      label.className = 'config-row-label';
      label.textContent = node.key;
      row.appendChild(label);
      for (const child of node.children) {
        renderNode(child, row);
      }
      container.appendChild(row);
      return;
    }

    const field = document.createElement('label');
    field.className = 'config-field';
    const labelText = document.createElement('span');
    labelText.textContent = node.path[node.path.length - 1];
    field.appendChild(labelText);

    const input = document.createElement('input');
    if (node.type === 'boolean') {
      input.type = 'checkbox';
      input.checked = node.value;
    } else if (node.type === 'number') {
      input.type = 'number';
      input.value = node.value;
    } else {
      input.type = 'text';
      input.value = node.value;
    }

    input.addEventListener('change', () => {
      let rawValue;
      if (node.type === 'boolean') rawValue = input.checked;
      else if (node.type === 'number') rawValue = Number(input.value);
      else if (node.type === 'json') rawValue = JSON.parse(input.value);
      else rawValue = input.value;

      working = applyEdit(working, node.path, rawValue);
    });

    field.appendChild(input);
    container.appendChild(field);
  }

  async function load() {
    const response = await fetch('/api/robot-config');
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      setStatus(body.error || 'Nie udało się wczytać configu', true);
      return;
    }
    working = await response.json();
    formEl.textContent = '';
    renderNode(buildFormTree(working), formEl);
  }

  if (saveBtn) {
    saveBtn.addEventListener('click', async () => {
      const response = await fetch('/api/robot-config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(working),
      });
      const body = await response.json().catch(() => ({}));
      if (response.ok) {
        setStatus('Zapisano', false);
      } else {
        setStatus(body.error || 'Błąd zapisu', true);
      }
    });
  }

  load();
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { buildFormTree, applyEdit, initConfigTab };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd site && npm test`
Expected: PASS for all tests in `config-tab.test.js`.

- [ ] **Step 5: Commit**

```bash
git add site/public/tabs/config.js site/tests/config-tab.test.js
git commit -m "feat: add config form builder and edit logic for site config tab"
```

---

### Task 3: Wire the Config tab into the page (HTML, app.js, CSS)

**Files:**
- Modify: `site/public/index.html:47` (sidebar), around `index.html:156-163` (add panel before `#tab-log` or after — placed last, after Log), `index.html:175` (script tag)
- Modify: `site/public/app.js:159-164` (tabInitializers array)
- Modify: `site/public/style.css`

**Interfaces:**
- Consumes: `initConfigTab` from `site/public/tabs/config.js` (Task 2), attached as a global via `<script>` tag (same as every other tab).
- Produces: working "Config" tab in the browser UI, DOM ids `config-form`, `config-save`, `config-status` referenced by `initConfigTab`.

- [ ] **Step 1: Add the sidebar button**

In `site/public/index.html`, in the `<nav class="sidebar">` block (line 39-48), add a new button after the Log button:

```html
        <nav class="sidebar">
          <button class="tab-button active" data-tab="control">Control</button>
          <button class="tab-button" data-tab="camera">Camera</button>
          <button class="tab-button" data-tab="gpio">GPIO</button>
          <button class="tab-button" data-tab="encoders">Enkodery</button>
          <button class="tab-button" data-tab="i2c">I2C</button>
          <button class="tab-button" data-tab="mic">Mikrofon</button>
          <button class="tab-button" data-tab="lidar">Lidar</button>
          <button class="tab-button" data-tab="log">Log</button>
          <button class="tab-button" data-tab="config">Config</button>
        </nav>
```

- [ ] **Step 2: Add the tab panel markup**

In `site/public/index.html`, immediately after the `</section>` that closes `#tab-log` (currently `index.html:163`) and before `</main>` (currently `index.html:164`), add:

```html
          <section id="tab-config" class="tab-panel">
            <div class="panel-card">
              <p class="panel-kicker">Ustawienia</p>
              <h2>Config</h2>
              <div id="config-form" class="config-form"></div>
              <div class="config-actions">
                <button id="config-save">Zapisz</button>
                <span id="config-status" class="config-status"></span>
              </div>
            </div>
          </section>
```

- [ ] **Step 3: Add the script tag**

In `site/public/index.html`, add before `<script src="app.js"></script>` (currently `index.html:176`):

```html
    <script src="tabs/config.js"></script>
```

- [ ] **Step 4: Register the tab initializer**

In `site/public/app.js`, update the `tabInitializers` array (currently lines 155-164):

```javascript
const tabInitializers = [
  typeof initControlTab === 'function' ? initControlTab : null,
  typeof initCameraTab === 'function' ? initCameraTab : null,
  typeof initGpioTab === 'function' ? initGpioTab : null,
  typeof initEncodersTab === 'function' ? initEncodersTab : null,
  typeof initI2cTab === 'function' ? initI2cTab : null,
  typeof initMicTab === 'function' ? initMicTab : null,
  typeof initLidarTab === 'function' ? initLidarTab : null,
  typeof initLogTab === 'function' ? initLogTab : null,
  typeof initConfigTab === 'function' ? initConfigTab : null,
];
```

- [ ] **Step 5: Add CSS for the generated form**

In `site/public/style.css`, append:

```css
.config-form {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  margin-top: 1rem;
}

.config-group {
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 0.75rem 1rem;
  margin: 0;
}

.config-group legend {
  padding: 0 0.4rem;
  color: var(--muted);
  text-transform: uppercase;
  font-size: 0.75rem;
  letter-spacing: 0.05em;
}

.config-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.config-row-label {
  color: var(--muted);
  min-width: 4rem;
}

.config-field {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  justify-content: space-between;
}

.config-field input[type="text"],
.config-field input[type="number"] {
  background: var(--panel-strong);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  padding: 0.4rem 0.6rem;
}

.config-actions {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-top: 1rem;
}

.config-status-ok {
  color: var(--success);
}

.config-status-error {
  color: var(--danger);
}
```

- [ ] **Step 6: Verify markup and script load with existing tab tests**

Run: `cd site && npm test`
Expected: PASS — this step is HTML/CSS/wiring only, existing tests are unaffected; this run confirms nothing else broke (e.g. no syntax errors in app.js).

- [ ] **Step 7: Manual smoke test in a browser**

Run: `cd site && npm start`

Open `http://localhost:3000` in a browser, click the "Config" tab, confirm:
- The form renders fields matching the real `config.json` at the repo root (e.g. `dev` checkbox, `gpio.chip` text field, `gpio.encoders.FL` row with two number inputs).
- Changing a value and clicking "Zapisz" shows "Zapisano" and the repo-root `config.json` on disk reflects the change (check with `cat ../config.json` from `site/`, or `git diff config.json` from repo root).
- Reloading the page shows the previously saved value (confirms the round trip).

Revert any accidental changes to the real `config.json` afterward with `git checkout -- config.json` if needed (check `git status`/`git diff` first, since `config.json` already had pre-existing uncommitted modifications per repo state).

- [ ] **Step 8: Commit**

```bash
git add site/public/index.html site/public/app.js site/public/style.css
git commit -m "feat: wire Config tab into site UI"
```

---

## Self-Review Notes

- **Spec coverage:** server routes (Task 1) ✓, form-tree UI with edit-only semantics (Task 2 + 3) ✓, explicit Save button flow (Task 2 `initConfigTab`, Task 3 wiring) ✓, tests for endpoints and pure helpers (Task 1 Step 1, Task 2 Step 1) ✓, `configPath` override for hermetic tests (Task 1) ✓, out-of-scope items (no add/remove keys, no schema validation, no live-reload of main.py) are honored by design — `buildFormTree`/`applyEdit` never introduce new keys and there's no UI affordance to do so.
- **Placeholder scan:** none — every step has complete code or an exact command with expected output.
- **Type consistency:** `buildFormTree`/`applyEdit`/`initConfigTab` signatures and the tree-node shape are defined once in Task 2 and reused verbatim in Task 3's wiring description; `configPath` option name matches between Task 1's `createApp` signature and its tests.
