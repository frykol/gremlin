# Config tab for site — design

## Problem

`config.json` (repo root) drives both `src/main.py` and `src/program_manager.py`. Today it can only be edited by SSH-ing into the robot and hand-editing the file. We want a tab in the existing `site` control panel (`site/`) that lets a user view and edit config values before starting the main program (clicking "Program ON").

## Constraint (not fixed by this change)

`program_manager.py` calls `load_config("config.json")` fresh every time it's started (`start_program_manager` in `src/main.py` spawns a new `python -m src.program_manager` process), so edits made before pressing "Program ON" take effect on the next start.

`main.py` itself reads config only once at process startup (WS bind address, `automatic_disconnect`, `disconnect_timeout`, `enable_site`). Editing those fields via the tab only takes effect after a full restart of `main.py` (which also restarts `site`). This is a pre-existing architectural property, not something this feature changes — the tab will edit the file correctly, but changes to those specific fields won't be picked up without restarting `main.py`.

## Server changes (`site/server.js`)

Add `express.json()` body parsing middleware (not currently present).

Two new routes, resolving the file at `path.join(__dirname, '..', 'config.json')`:

- `GET /api/robot-config`
  - Reads and parses `config.json`.
  - 200 with the parsed object on success.
  - 404 with `{ error }` if the file doesn't exist.
  - 500 with `{ error }` if it exists but fails to parse.

- `PUT /api/robot-config`
  - Body must be a JSON object (`req.body`), enforced by `express.json()`.
  - 400 with `{ error }` if body is missing, not an object, or is an array/null.
  - On success: `JSON.stringify(body, null, 2) + '\n'` written to `config.json`, response 200 `{ success: true }`.
  - 500 with `{ error }` if the write fails (e.g. permissions).
  - No key-structure validation against the previous file — the client only ever submits a shape it read from `GET /api/robot-config` with values edited in place, so structural drift isn't expected from this UI. The route accepts whatever object it's given, so it stays simple and doesn't need updating when config.json's schema changes.

The `path` module resolution is testable the same way the existing `createApp` tests work — `createApp` should accept an optional `configPath` override (default `path.join(__dirname, '..', 'config.json')`) so tests can point it at a temp file instead of the real repo config.

## Client changes

### New file: `site/public/tabs/config.js`

Exports `initConfigTab(context)` (same pattern as other tabs) plus pure helper functions used both by the tab and by tests:

- `buildFormTree(value, path)` — recursively walks a JS value and returns a description of DOM nodes to render (object → group of labeled fields per key; array → row of one input per element, index-labeled; boolean → checkbox; number/string → text/number input; anything else → JSON.stringify'd text input as a fallback so no data is silently dropped). Each leaf carries its `path` (array of keys/indices) so edits can be written back into a cloned object without adding/removing keys.
- `applyEdit(root, path, rawValue)` — clones `root`, sets the value at `path` (coercing to number/boolean as the original type dictates), returns the new object. Never inserts new keys or array entries — only overwrites existing ones.
- `initConfigTab(context)` — on init: `fetch('/api/robot-config')`, render the tree into `#config-form`, wire input `change` listeners to call `applyEdit` and keep an in-memory working copy, wire the Save button to `PUT /api/robot-config` with the working copy and show a status message (`#config-status`) on success/error.

This tab does not use `context.sendControl` / WS — it's local-only (file lives on the same machine running `site`), consistent with `/api/config` already being a plain `fetch`.

### `site/public/index.html`

- New sidebar button: `<button class="tab-button" data-tab="config">Config</button>`
- New panel `#tab-config` with a panel-card containing `#config-form` (container the tab script populates) and a "Zapisz" button (`#config-save`) plus a status element (`#config-status`).
- New `<script src="tabs/config.js"></script>` before `app.js`.

### `site/public/app.js`

Add `typeof initConfigTab === 'function' ? initConfigTab : null` to the `tabInitializers` array, same pattern as the others.

## Testing

- `site/tests/config_endpoint.test.js`: extend with cases for `GET /api/robot-config` (happy path, missing file → 404, malformed JSON on disk → 500) and `PUT /api/robot-config` (happy path round-trip, non-object body → 400, verifying the file content after a successful PUT). Use `createApp({ configPath: <tmp file> })` so tests never touch the real repo `config.json`.
- New `site/tests/config-tab.test.js`: unit tests for `buildFormTree` and `applyEdit` against representative shapes from the real config (nested objects, an array of numbers like `encoders.FL`, booleans, `is_dummy`-style flags) — confirms values round-trip and no keys are added/removed.

## Out of scope

- No schema validation of config values (e.g. checking `port` is in valid range).
- No diffing/undo — Save overwrites the whole file.
- No live-reload of `main.py`'s own already-loaded config.
- No adding/removing keys or array elements from the UI (explicit user requirement).
