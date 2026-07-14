# Control Page Feature Parity — Design

Date: 2026-07-14
Status: Approved for planning

## Goal

Port the full control surface of the old Tkinter desktop interface
(`interface/` on the `interface` branch: `Control_view.py`, `Camera_view.py`,
`GPIO_view.py`, `I2C_view.py`, `Mic_view.py`, `Log_view.py`, plus `app.py`'s
program ON/OFF button) onto the new browser-based control page built in the
prior WS-server-rewrite work (`site/public/`). All tabs are ported in one
pass, not staged.

## Non-goals

- No audio recording-to-file in the browser (Web Audio playback + level
  meter only, per explicit decision — recording can be a future addition).
- No change to the underlying command semantics already wired end-to-end
  from the WS rewrite (`gpio`, `motor`, `stream`, `audio_stream`,
  `set_program_status`, `get_program_status`, `{"send":"logs"}`,
  `register_video_sink`) — this task is UI, not protocol redesign, except
  for the one new message described below.
- No server-side camera rotation. The old Tkinter app rotated the
  displayed image locally (PIL) and also emitted a `{"type":"rotate"}` WS
  message that nothing on the robot side has ever handled (confirmed via
  `grep -rn "rotate" src/` — zero matches outside the old Tkinter code).
  This port keeps rotation entirely client-side (CSS transform) and drops
  the inert WS message.
- No new build tooling/framework — same plain HTML/CSS/JS approach as the
  existing control page.

## Architecture

Single HTML page, tab-based (mirroring the old sidebar), each tab as an
isolated JS module with one render function + one set of event handlers,
sharing one control WebSocket connection (already established by the prior
work) and the existing video-relay WebSocket (unchanged).

```
site/public/
  index.html       - shell: header (IP form, status, program ON/OFF), sidebar tabs, tab content mount points
  style.css         - existing styles + tab layout + per-tab widget styles
  app.js            - existing connection logic (control WS, video WS) + tab-switching + program ON/OFF wiring
  tabs/
    control.js       - driving controls (buttons, arrow keys, power slider)
    camera.js        - video panel controls: start/stop stream, capture, rotate (extends existing <img>)
    gpio.js           - 40-pin grid
    i2c.js            - per-channel PWM sliders
    mic.js            - audio level meter + Web Audio playback
    log.js            - log viewer, polls {"send":"logs"}, clear button
```

Each tab module exports `init(context)` where `context` provides:
- `sendControl(message)` — JSON-stringifies and sends over the shared control WS (no-ops if not connected, matching existing `WsServer`/frontend semantics).
- `onControlMessage(handler)` — subscribe to incoming JSON messages from the control WS, filtered by `type` inside the handler (mirrors how the old Tkinter `app.py` dispatched `audio_chunk`/`get_program_status`/log-file messages to different views).

`app.js` owns the single control WS instance and fans incoming messages out to whichever tab(s) registered a handler; it does not need per-tab knowledge of message shapes.

## Component behavior (parity with old Tkinter views)

### Control tab (`Control_view.py` → `control.js`)
- Same six directions (Przód/Tył/Lewo/Prawo/Full lewo/Full prawo), same `directions` → channel-index mapping table, same motor-pair channel layout (0/1, 2/3, 5/4, 7/6).
- Power slider 0-100% → PWM 0-4095, same formula (`pct/100 * 4095`).
- Input sources: on-screen buttons (press/release) AND arrow keys + Shift (held), combined into an `activeDirections` set exactly like the Python version's `pressed_buttons ∪ {Up→Przód, Down→Tył, Left/Shift+Left→Lewo/Full lewo, Right/Shift+Right→Prawo/Full prawo}`.
- Sends `{"type":"motor","channel":n,"pwm":v}` per channel, only on change (same `last_sent_values` dedup pattern), status label reflects active directions (green/red).
- Key-release debounce: the Python version delays release processing by 20ms (`self.after(20, ...)`) to smooth key-repeat; replicate with a `setTimeout(..., 20)` per key.

### Camera tab (`Camera_view.py` → `camera.js`)
- Reuses the existing video `<img>` element from the prior work; adds Start/Stop buttons sending `{"type":"stream","enabled":true/false}` (already-wired command).
- Rotate button toggles a CSS class applying `transform: rotate(180deg)` to the `<img>` — client-side only, no WS message.
- Capture button: draws the current `<img>` onto an off-screen `<canvas>`, calls `canvas.toBlob(...)`, and triggers a download via a temporary `<a>` element — no backend involved (parity with the old app's local `.jpg` save, adapted to a browser download since there's no shared filesystem between browser and site server).

### GPIO tab (`GPIO_view.py` → `gpio.js`)
- Same physical-pin-to-name table (`GPIO_PINS` — pins 7,11,13,15,16,18,22,29,31,32,33,36,37 → GPIO4/17/27/22/23/24/25/5/6/12/13/16/26), rendered as a 2-column grid, non-mapped pins shown disabled.
- Click selects a pin (highlight), then 0/1 buttons send `{"type":"gpio","pin_name":"GPIO4","value":0|1}` for the currently-selected pin — same interaction model (select-then-set, not click-to-toggle) as the original.
- Button color reflects last-set value (red=0, green=1) per pin, same as `update_button`.

### I2C tab (`I2C_view.py` → `i2c.js`)
- Same 8 labeled channel buttons ("LP przód", "LP tył", "LT przód", "LT tył", "PP tył", "PP przód", "PT tył", "PT przód"), same channel indices 0-7.
- One shared slider (0-100) applies to whichever channel is currently selected; selecting a channel loads its last value into the slider (same `set_active` behavior).
- Same "opposite channel" safety: setting one channel of a pair (`i ^ 1` — 0↔1, 2↔3, 4↔5, 6↔7) to nonzero force-zeroes its pair first, sending an explicit stop for it, matching `on_change`'s `opposite_index` logic.
- Sends `{"type":"motor","channel":n,"pwm":round(v*40.95)}` (0-100 → 0-4095, matching `int(value * 40.95)`).

### Mic tab (`Mic_view.py` → `mic.js`)
- Start/Stop buttons send `{"type":"audio_stream","enabled":true/false}` (already-wired).
- On `audio_chunk` messages (base64 PCM16 mono, `sample_rate`, `chunk_id`): decode base64 → `Int16Array` → normalize to `Float32Array` for playback.
- Level meter: same peak-based percentage calculation (`max(abs(samples))/32768*100`), rendered as a colored bar (green <70%, orange <90%, red ≥90%) matching `_draw_level`'s thresholds — implemented with a `<canvas>` or a styled `<div>` bar, either is fine.
- Playback: feed decoded Float32 samples into a Web Audio `AudioBufferSourceNode` (or `ScriptProcessorNode`/`AudioWorklet` if simple buffering needs it — implementer's choice, whichever is less code for chunk-by-chunk playback without audible gaps) at the chunk's `sample_rate`. A "Odsłuch" checkbox gates whether playback is active, mirroring `playback_var`.
- No recording controls (explicitly out of scope).

### Log tab (`Log_view.py` → `log.js`)
- Polls the robot every 500ms while the tab is active (or continuously, matching the Python app's unconditional `self.after(500, poll_host_logs)` — simplest to just always poll once connected, same as today's `get_program_status` heartbeat pattern) by sending `{"send":"logs"}` over the control WS.
- On the `{"type":"logs","file":"<base64>"}` response (already sent by `CommandProcessor._send_log`, unchanged), base64-decode, and re-render the log text only if content changed (same dedup as `_last_content`).
- Same line-tagging: lines containing "ERROR"/"CRITICAL" (case-insensitive) styled red, "SYSTEM" styled blue, "INFO" styled green, matching the old `tag_config` colors.
- "Wyczyść Logi" button sends a **new** message type `{"type":"clear_logs"}`.

### Program ON/OFF (`app.py`'s sidebar button → wired into `app.js`'s header)
- Two buttons (ON/OFF) send `{"type":"set_program_status","status":"on"|"off"}` (already-wired command, just missing a UI trigger today).
- A status indicator polls via periodic `{"type":"get_program_status"}` (matching the old app's unconditional 500ms poll) and renders the `{"type":"get_program_status","status":"on"|"off"}` reply, plus reacts to unsolicited `{"type":"program_status", status, success, message}` pushes from `main.py` (sent after `start_program_manager`/`stop_program_manager` calls, and by the heartbeat auto-disconnect path) — same two message shapes the old Tkinter app already handled.

## New backend piece: `clear_logs`

**Why it can't just forward through the existing pipe path:** the log file
(`sim.log`) is opened and owned by `main.py` itself (the parent process,
not the `program_manager` child) — see `src/main.py`'s
`log_file = open(SIM_LOG, "a", ...)`. Clearing it needs to work whether or
not `program_manager` is currently running (a user should be able to clear
logs without having started the robot program), so it must be intercepted
directly in `main.py`'s `handle_instruction`, the same way
`get_program_status`/`set_program_status` already are — not routed to
`CommandProcessor` in the child.

**Behavior:** on receiving `{"type":"clear_logs"}`, `main.py`:
1. Closes the current `log_file` handle.
2. Truncates `sim.log` (open in `"w"` mode, immediately close — this also
   handles the file not existing yet).
3. Reopens `log_file` in append mode (same as startup), so the
   `_patched_print` builtin keeps working afterward.
4. Sends back `{"type":"clear_logs","success":true}` so the frontend can
   confirm (matching the ack-style pattern already used by
   `send_ws_status` for `set_program_status`).

This is the only backend/protocol change in this task; everything else
routes through message types that already work end-to-end.

## Testing

- Python: one new test for `clear_logs` handling — since `handle_instruction`
  is a closure inside `main()` (same constraint hit during the prior WS
  rewrite's final-review fix), test at the same level that fix used:
  a direct test of the log-file truncate/reopen behavior in isolation
  (e.g. extract the truncate steps into a small top-level helper function
  if that keeps it testable without refactoring `main()`'s control flow —
  implementer's call, following the precedent set by the previous task).
- JS: no browser test harness exists (same constraint as the prior
  control-page work) — each tab's pure-logic pieces that don't touch the
  DOM (motor-channel mapping math, PWM scaling, log line tagging, base64
  PCM decoding) should be extracted into plain functions and unit-tested
  with `node --test`, following the pattern already used for
  `createVideoRelay`. DOM wiring itself is manually verified.
- Manual verification (real hardware, like the prior Task 9): drive the
  robot via Control tab, verify GPIO/I2C manual overrides reach hardware,
  verify camera capture/rotate, verify mic level+playback, verify log tab
  shows real log content and clear works, verify program ON/OFF toggles
  `program_manager`.
