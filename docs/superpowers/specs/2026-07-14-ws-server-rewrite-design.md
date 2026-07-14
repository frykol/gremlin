# WS Server Rewrite + Control Website — Design

Date: 2026-07-14
Status: Approved for planning

## Goal

Today, `main.py` on the robot is a WebSocket **client** that dials out to an
external WS server (`ws_server.host/port` in `config.json`), which was meant
to be provided by a website backend. No such website exists yet.

We're flipping this: `main.py` becomes the WS **server**, and a browser page
connects to it directly to control the robot. We're also building the
website (Express) that serves that control page, plus a small UDP relay so
the browser can see the camera stream (browsers can't open raw UDP sockets).

## Non-goals

- No changes to `program_manager`, `os.pipe()` IPC, `CommandProcessor`,
  `RobotController`, or any hardware modules. Those keep working exactly as
  they do today — only the transport at the outer edge of `main.py` changes
  from WS-client to WS-server.
- No auth/security hardening (local network use only, matches current state).
- No changes to audio streaming (still goes over the existing WS message
  channel via `AudioStreamer`, just now server-side).
- Camera pixel encoding/format is unchanged — only the transport path from
  robot to browser is new.

## Architecture

```
Browser                         Express (Node, site host)         main.py (Pi, WS server)      program_manager (child, pipes)
  |-- WS control ws://<robot-ip>:8765 ------------------------------->|
  |                                                                    |-- pipe --> CommandProcessor -> hardware
  |<-------------------------------------------------------------------|
  |                                    |<--- UDP camera frames --------|  (main.py sends once it knows the sink)
  |<-- WS video relay ------------------|
  |
  |-- HTTP GET / (control page, IP entry form) --> Express
```

Two independent connections from the browser:

1. **Control WS** — browser → `main.py` directly. JSON command/status
   messages, same shape as today (`gpio`, `motor`, `stream`,
   `set_program_status`, `program_status`, `logs`, etc.).
2. **Video relay WS** — browser → Express. Express owns a UDP socket that
   receives camera frames from the robot and re-emits each frame as a
   binary WS message to the browser.

The robot doesn't need to know Express exists until the browser tells it,
over the control WS, where to send frames.

## Component changes

### 1. `main.py` (WS client → WS server)

- Replace `WSClient`/`ws.connect()` with `websockets.asyncio.server.serve()`.
- Single active connection: accepting a new connection closes the previous
  one first (send a close frame, then accept). No connection queueing.
- All existing logic that reads from `instruction_tab` and writes to
  `ws.send(...)` stays as-is — the `WSClientInterface` used internally by
  `PipeWSClient` (talking to `program_manager`) is untouched. Only the
  outward-facing object (today's `WSClient`) is replaced by a thin
  server-side wrapper exposing the same `send`/`close` surface main.py
  already calls, so `handle_instruction`, `send_ws_status`, etc. don't
  change.
- New inbound message type, handled alongside the existing `gpio`/`motor`/
  `set_program_status` cases in `main.py`'s dispatch (not inside
  `CommandProcessor`, since this concerns the outer transport, not robot
  hardware):
  ```json
  { "type": "register_video_sink", "host": "<express-ip>", "port": 9000 }
  ```
  On receipt, main.py updates the `UdpFrameSender` target (add a
  `set_target(host, port)` method) so `CameraStreamer` starts sending
  frames there. If no sink is registered yet, frames are simply dropped
  (current behavior when nothing listens on the UDP port already amounts to
  this).
- `config.json`'s `ws_server.host` is no longer used for dialing out; it's
  repurposed (or a new `ws_server.port`/`bind_host` key added) as the
  bind address for the server (default `0.0.0.0:8765`).
- `camera_stream.udp_host/udp_port` in `config.json` become just the
  startup default sink (kept for backward compatibility / no-browser
  testing); the registered sink from the browser overrides it at runtime.

### 2. Express site (new: `site/` directory)

- Static page (`public/index.html` + JS) served via `express.static`.
- One small Node backend (`server.js`):
  - Serves the static page.
  - Runs a `dgram` UDP socket bound to a fixed port (e.g. 9000) to receive
    camera frames from the robot.
  - Runs its own WS server (e.g. `ws` package) that the browser's video
    channel connects to; each UDP datagram received is forwarded verbatim
    as a binary WS frame to the connected browser.
  - Does **not** proxy the control channel — that's a direct browser→robot
    connection, so Express stays simple (no relaying command traffic).

### 3. Frontend page

- Form: text input for robot IP + "Connect" button.
- On submit:
  1. Open `new WebSocket('ws://<ip>:8765')` (control).
  2. On control-WS open, send `register_video_sink` with Express's own
     UDP-listener address (the page knows this because it knows its own
     host and a fixed port shared with `server.js`'s config).
  3. Open a second WS to Express's video-relay endpoint (`ws://<site-host>/video`).
- Connection indicator: simple colored dot + text ("Connected" /
  "Disconnected" / "Connecting…"), driven by the control WS's
  `onopen`/`onclose`/`onerror`. Video WS state is not shown separately for
  now.
- Reconnect: manual only for this iteration (user re-clicks Connect) — no
  automatic retry loop, to keep this iteration's scope small.

## Data flow / message contract (control channel)

No changes to existing message shapes (`gpio`, `motor`, `stream`,
`audio_stream`, `get_program_status`, `set_program_status`,
`program_status`, `logs`). Only addition is `register_video_sink` described
above, handled in `main.py` before/alongside the existing
`handle_instruction` dispatch.

## Error handling

- If the browser's control WS drops, `main.py` treats it like today's
  disconnect path (the existing `automatic_disconnect`/heartbeat logic in
  `main.py` is unaffected — it already only cares about
  `get_program_status` timing, not the transport direction).
- If a second browser tries to connect while one is active, `main.py`
  closes the *existing* connection (with a close reason like
  `"replaced by new connection"`) and accepts the new one. This matches
  "single client, newest wins" from the requirements.
- If Express's UDP relay has no browser connected yet, it just drops
  incoming datagrams (mirrors current no-listener behavior).

## Testing

- Existing `tests/test_websocket_config.py` needs updating for the new
  server-mode config/behavior (whatever it currently asserts about the
  client path).
- New unit coverage: `main.py`'s WS-server message dispatch (register +
  existing instruction forwarding to the child pipe) using a fake
  websocket connection, and `register_video_sink` updating
  `UdpFrameSender`'s target.
- Express: basic test that a UDP datagram received gets relayed to a
  connected mock WS client.
- Manual verification: open the page, enter the Pi's IP, confirm indicator
  goes green, confirm a command (e.g. GPIO toggle) reaches hardware, confirm
  video frames arrive (this needs real hardware / the Pi, so call out
  explicitly in the plan as a manual step, not an automated test).
