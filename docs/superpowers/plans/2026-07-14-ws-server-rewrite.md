# WS Server Rewrite + Control Website Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flip `main.py` from a WebSocket client (dialing out to a site server) to a WebSocket server that the browser connects to directly, and build the Express-based control website (IP-entry form, connection indicator, video relay) that talks to it.

**Architecture:** `main.py` hosts a single-client WS server (`websockets.asyncio.server`) at the same call sites where it used to hold a WS client — `handle_instruction`, `send_ws_status`, the pipe-to-child forwarding, and the heartbeat logic are untouched. A new `register_video_sink` message flows through the existing pipe path to `CommandProcessor`, which now owns a reference to `UdpFrameSender` and repoints it at the browser-side relay. The Express site is a static file server plus a UDP→WS video relay; the browser's page opens two connections — one directly to the robot for control, one to Express for video.

**Tech Stack:** Python 3.13, `websockets` 16.0 (already a dependency), `pytest` (already installed in `.venv`), Node 20 + Express + `ws` for the new `site/` directory, plain HTML/CSS/JS for the frontend (no frontend build step / framework).

## Global Constraints

- Do not modify `program_manager`, `os.pipe()` IPC, `RobotController`'s task wiring, or any hardware module beyond what's specified in a task below.
- Existing WS message shapes (`gpio`, `motor`, `stream`, `audio_stream`, `get_program_status`, `set_program_status`, `program_status`, `send:"logs"`, `audio_chunk`) must keep working unmodified — this rewrite only changes transport direction and adds `register_video_sink`.
- Single active browser connection to `main.py`'s WS server: a new connection closes the previous one first.
- Python tests run via `.venv/bin/python3 -m pytest <path> -v` from the repo root.
- Node tests run via `node --test` from inside `site/`.
- Follow existing code style: no type-hint decoration beyond what's already used in each file, no comments unless explaining non-obvious behavior (matches the rest of the codebase).

---

### Task 1: `websocket_config.build_bind_address`

The current `tests/test_websocket_config.py` imports `src.websocket_config.build_ws_uri`, a module that was never created (orphaned test from an earlier commit, confirmed via `git log -- tests/test_websocket_config.py` — only one commit, `64c0b91`, touches it, and `src/websocket_config.py` doesn't exist anywhere in history). Replace it with a real module used by `main.py` to compute the server's bind address.

**Files:**
- Create: `src/websocket_config.py`
- Modify: `tests/test_websocket_config.py` (full rewrite)

**Interfaces:**
- Produces: `build_bind_address(config: dict) -> tuple[str, int]`, reading `config["ws_server"]["bind_host"]` (default `"0.0.0.0"`) and `config["ws_server"]["port"]` (default `8765`). Used by Task 5.

- [ ] **Step 1: Write the failing test**

Replace the full contents of `tests/test_websocket_config.py`:

```python
from src.websocket_config import build_bind_address


def test_build_bind_address_uses_configured_values():
    config = {
        "ws_server": {
            "bind_host": "10.0.0.5",
            "port": 9000,
        }
    }

    assert build_bind_address(config) == ("10.0.0.5", 9000)


def test_build_bind_address_defaults_to_all_interfaces():
    assert build_bind_address({}) == ("0.0.0.0", 8765)


def test_build_bind_address_defaults_port_when_only_host_given():
    config = {"ws_server": {"bind_host": "192.168.1.50"}}

    assert build_bind_address(config) == ("192.168.1.50", 8765)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_websocket_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.websocket_config'`

- [ ] **Step 3: Write minimal implementation**

Create `src/websocket_config.py`:

```python
def build_bind_address(config: dict) -> tuple[str, int]:
    ws_config = config.get("ws_server", {})
    host = ws_config.get("bind_host", "0.0.0.0")
    port = ws_config.get("port", 8765)
    return host, port
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_websocket_config.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/websocket_config.py tests/test_websocket_config.py
git commit -m "feat: add websocket_config.build_bind_address for WS server bind address"
```

---

### Task 2: `UdpFrameSender.set_target`

Allow retargeting the UDP destination at runtime, so the browser's registered video-relay address can override the config-file default.

**Files:**
- Modify: `src/dev_connection/udp_frame_sender.py`
- Test: `tests/test_udp_frame_sender.py` (new)

**Interfaces:**
- Consumes: nothing new.
- Produces: `UdpFrameSender.set_target(host: str, port: int) -> None`, updating `self.host`/`self.port` used by `send_frame`. Used by Task 4.

- [ ] **Step 1: Write the failing test**

Create `tests/test_udp_frame_sender.py`:

```python
from unittest.mock import MagicMock

from src.dev_connection.udp_frame_sender import UdpFrameSender


def test_set_target_updates_destination_used_by_send_frame():
    sender = UdpFrameSender(host="192.168.1.162", port=8766)
    sender._socket = MagicMock()

    sender.set_target("10.0.0.9", 9000)
    sender.send_frame(frame_id=1, timestamp=1.0, payload=b"x")

    sent_addr = sender._socket.sendto.call_args[0][1]
    assert sent_addr == ("10.0.0.9", 9000)


def test_set_target_before_any_send_is_used_immediately():
    sender = UdpFrameSender(host="old-host", port=1)
    sender._socket = MagicMock()

    sender.set_target("new-host", 2)

    assert sender.host == "new-host"
    assert sender.port == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_udp_frame_sender.py -v`
Expected: FAIL with `AttributeError: 'UdpFrameSender' object has no attribute 'set_target'`

- [ ] **Step 3: Write minimal implementation**

In `src/dev_connection/udp_frame_sender.py`, add a method to the `UdpFrameSender` class (after `__init__`):

```python
    def set_target(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_udp_frame_sender.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/dev_connection/udp_frame_sender.py tests/test_udp_frame_sender.py
git commit -m "feat: add UdpFrameSender.set_target for runtime video sink registration"
```

---

### Task 3: `WsServer` (server-side replacement for `WSClient`)

A drop-in replacement for `WSClient` that hosts a WS server instead of dialing out, enforcing single-connection-replace semantics, exposing the same `send`/`close`/`connect` surface `main.py` already calls.

**Files:**
- Create: `src/dev_connection/ws_server.py`
- Test: `tests/test_ws_server.py` (new)

**Interfaces:**
- Consumes: `websockets.asyncio.server.serve` (already a project dependency, version 16.0 confirmed in `.venv`).
- Produces: `WsServer(host: str, port: int, instruction_tab: asyncio.Queue)` with:
  - `async def connect(self) -> None` — binds and serves forever (call site identical to today's `ws.connect()` in `main.py`).
  - `async def send(self, message: str) -> None` — sends to the currently active connection, no-ops with a printed message if none.
  - `async def close(self) -> None` — closes the active connection and the server.
  - Internal `async def _handler(self, websocket) -> None` — accepts one connection, closing any previous one first, and forwards decoded JSON messages into `instruction_tab` (mirrors `WSClient.listen`). Exposed as a "private" method specifically so Task 3's tests can drive it directly without opening real sockets.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ws_server.py`:

```python
import asyncio
import json

from src.dev_connection.ws_server import WsServer


class FakeConnection:
    def __init__(self, messages):
        self._messages = list(messages)
        self.sent = []
        self.closed = False
        self.close_reason = None

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)

    async def send(self, message):
        self.sent.append(message)

    async def close(self, reason=None):
        self.closed = True
        self.close_reason = reason


def test_handler_forwards_messages_to_instruction_tab():
    async def run_test():
        instruction_tab = asyncio.Queue()
        server = WsServer("0.0.0.0", 8765, instruction_tab)

        conn = FakeConnection([json.dumps({"type": "gpio", "pin_name": "GPIO4", "value": 1})])
        await server._handler(conn)

        msg = instruction_tab.get_nowait()
        assert msg == {"type": "gpio", "pin_name": "GPIO4", "value": 1}

    asyncio.run(run_test())


def test_handler_closes_previous_connection_when_new_one_arrives():
    async def run_test():
        instruction_tab = asyncio.Queue()
        server = WsServer("0.0.0.0", 8765, instruction_tab)

        first = FakeConnection([])
        # Keep the first connection "active" by not letting its handler task
        # finish before the second one connects: call _handler for the first
        # without awaiting its message loop completion semantics — instead,
        # directly exercise the replace path by handling a first connection
        # in a background task that blocks on an event.
        block = asyncio.Event()

        class BlockingConnection(FakeConnection):
            def __aiter__(self):
                return self

            async def __anext__(self):
                await block.wait()
                raise StopAsyncIteration

        blocking_first = BlockingConnection([])
        first_task = asyncio.create_task(server._handler(blocking_first))
        await asyncio.sleep(0)  # let first_task register as the active connection

        second = FakeConnection([])
        await server._handler(second)

        assert blocking_first.closed is True
        assert blocking_first.close_reason == "replaced by new connection"

        block.set()
        await first_task

    asyncio.run(run_test())


def test_send_no_ops_when_nothing_connected():
    async def run_test():
        instruction_tab = asyncio.Queue()
        server = WsServer("0.0.0.0", 8765, instruction_tab)

        await server.send("hello")  # must not raise

    asyncio.run(run_test())


def test_send_delivers_to_active_connection():
    async def run_test():
        instruction_tab = asyncio.Queue()
        server = WsServer("0.0.0.0", 8765, instruction_tab)

        conn = FakeConnection([])
        await server._handler(conn)

        await server.send("hello")

        assert conn.sent == ["hello"]

    asyncio.run(run_test())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_ws_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.dev_connection.ws_server'`

- [ ] **Step 3: Write minimal implementation**

Create `src/dev_connection/ws_server.py`:

```python
import json

from websockets.asyncio.server import serve


class WsServer:
    def __init__(self, host, port, instruction_tab):
        self.host = host
        self.port = port
        self.instruction_tab = instruction_tab
        self._connection = None
        self._server = None

    async def connect(self):
        self._server = await serve(self._handler, self.host, self.port)
        await self._server.serve_forever()

    async def _handler(self, websocket):
        if self._connection is not None:
            try:
                await self._connection.close(reason="replaced by new connection")
            except Exception:
                pass

        self._connection = websocket

        try:
            async for message in websocket:
                json_message = json.loads(message)
                await self.instruction_tab.put(json_message)
        finally:
            if self._connection is websocket:
                self._connection = None

    async def send(self, message):
        if self._connection is None:
            print("Websocket not connected")
            return
        await self._connection.send(message)

    async def close(self):
        if self._connection is not None:
            try:
                await self._connection.close()
            except Exception:
                pass
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_ws_server.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/dev_connection/ws_server.py tests/test_ws_server.py
git commit -m "feat: add WsServer, a single-connection WS server replacing the outbound WS client"
```

---

### Task 4: `register_video_sink` in `CommandProcessor` + wiring in `RobotController`

`UdpFrameSender` lives in `RobotController` (the `program_manager` child process), not in `main.py`. The `register_video_sink` message therefore needs no special-casing in `main.py` — it already forwards any message it doesn't intercept straight to the child over the existing pipe. It just needs a handler in `CommandProcessor`, which already receives hardware objects and dispatches on `cmd.get("type")`.

**Files:**
- Modify: `src/services/command_processor.py`
- Modify: `src/robot_controller.py`
- Test: `tests/test_command_processor.py` (new)

**Interfaces:**
- Consumes: `UdpFrameSender.set_target(host, port)` from Task 2.
- Produces: `CommandProcessor(command_queue, gpio, i2c_pwm, state, ws, udp_frame_sender)` — note the added trailing constructor parameter — and a `register_video_sink` command type: `{"type": "register_video_sink", "host": <str>, "port": <int>}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_command_processor.py`:

```python
import asyncio

from src.services.command_processor import CommandProcessor
from src.robot_state import RobotState


class DummyUdpFrameSender:
    def __init__(self):
        self.calls = []

    def set_target(self, host, port):
        self.calls.append((host, port))


class DummyGpio:
    pins = {}
    standard_pins = {}


class DummyI2cPwm:
    def set_pwm(self, channel, on, off):
        pass


class DummyWs:
    async def send(self, message):
        pass


def test_register_video_sink_updates_udp_frame_sender_target():
    async def run_test():
        queue = asyncio.Queue()
        udp_frame_sender = DummyUdpFrameSender()
        processor = CommandProcessor(
            command_queue=queue,
            gpio=DummyGpio(),
            i2c_pwm=DummyI2cPwm(),
            state=RobotState(),
            ws=DummyWs(),
            udp_frame_sender=udp_frame_sender,
        )

        queue.put_nowait({"type": "register_video_sink", "host": "10.0.0.9", "port": 9000})
        await processor.process_commands()

        assert udp_frame_sender.calls == [("10.0.0.9", 9000)]

    asyncio.run(run_test())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_command_processor.py -v`
Expected: FAIL with `TypeError: CommandProcessor.__init__() got an unexpected keyword argument 'udp_frame_sender'`

- [ ] **Step 3: Write minimal implementation**

In `src/services/command_processor.py`, update the constructor and add the new branch:

```python
class CommandProcessor:
    def __init__(self, command_queue: asyncio.Queue, gpio: GPIOController, i2c_pwm: i2cPWM, state: RobotState, ws: WSClientInterface, udp_frame_sender):
        self.command_queue: asyncio.Queue = command_queue
        self.gpio: GPIOController = gpio
        self.i2c_pwm: i2cPWM = i2c_pwm
        self.state: RobotState = state
        self.ws: WSClientInterface = ws
        self.udp_frame_sender = udp_frame_sender
```

Add this branch inside `process_commands`, alongside the existing `elif` chain (after the `audio_stream` branch):

```python
                elif cmd.get("type") == "register_video_sink":
                    self.udp_frame_sender.set_target(cmd["host"], cmd["port"])
```

Now update `src/robot_controller.py` to construct `UdpFrameSender` before `CommandProcessor` (today it's built after) and pass it through. Move the `self.udp_frame_sender = UdpFrameSender(...)` block (currently built from `camera_stream_config` further down in `__init__`) to just above the existing `self.command_processor = CommandProcessor(...)` block, and add the new argument:

```python
        camera_stream_config = config.get("camera_stream", {})

        self.udp_frame_sender = UdpFrameSender(
            host=camera_stream_config.get("udp_host", "192.168.1.162"),
            port=camera_stream_config.get("udp_port", 8766),
            chunk_size=camera_stream_config.get("chunk_size", 1400),
        )

        self.command_processor = CommandProcessor(
            command_queue=command_queue,
            gpio=gpio,
            i2c_pwm=i2c_pwm,
            state=self.state,
            ws=ws,
            udp_frame_sender=self.udp_frame_sender,
        )
```

Remove the now-duplicate later `UdpFrameSender`/`camera_stream_config` construction further down in the file (it previously sat between `mic_worker`/`voice_worker` setup and `camera_streamer` setup) — the single instance created above is reused by `self.camera_streamer = CameraStreamer(udp_sender=self.udp_frame_sender, ...)`, which stays where it is.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_command_processor.py -v`
Expected: 1 passed

Then run the full Python suite to confirm nothing else broke from the constructor signature change:

Run: `.venv/bin/python3 -m pytest tests/ -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/services/command_processor.py src/robot_controller.py tests/test_command_processor.py
git commit -m "feat: handle register_video_sink in CommandProcessor, wire UdpFrameSender through"
```

---

### Task 5: `main.py` — swap `WSClient` for `WsServer`

**Files:**
- Modify: `src/main.py:1-11` (imports), `src/main.py:94-104` (connection setup)

**Interfaces:**
- Consumes: `build_bind_address` from Task 1, `WsServer` from Task 3.
- Produces: no new public interface — `main()`'s internal `ws` variable is now a `WsServer` instance, but every call site (`ws.send`, `ws.close`, `ws_task = asyncio.create_task(ws.connect())`) is unchanged, so `handle_instruction`, `send_ws_status`, `handle_child_response`, and `monitor_heartbeat` require no edits.

- [ ] **Step 1: Update the import**

In `src/main.py`, replace:

```python
from .dev_connection.client import WSClient
```

with:

```python
from .dev_connection.ws_server import WsServer
from .websocket_config import build_bind_address
```

- [ ] **Step 2: Update connection setup**

In `src/main.py`, replace lines 96-104:

```python
    config = load_config("config.json")

    # Build websocket URI from config
    ws_host = config.get("ws_server", {}).get("host", "192.168.1.162")
    ws_port = config.get("ws_server", {}).get("port", 8765)
    ws_uri = f"ws://{ws_host}:{ws_port}"

    instruction_tab = asyncio.Queue()
    ws = WSClient(ws_uri, instruction_tab)
    ws_task = asyncio.create_task(ws.connect())
```

with:

```python
    config = load_config("config.json")

    bind_host, bind_port = build_bind_address(config)

    instruction_tab = asyncio.Queue()
    ws = WsServer(bind_host, bind_port, instruction_tab)
    ws_task = asyncio.create_task(ws.connect())
```

- [ ] **Step 3: Run the existing main.py test to confirm nothing broke**

Run: `.venv/bin/python3 -m pytest tests/test_main_pipe_handling.py -v`
Expected: 1 passed (this test only exercises `_write_instruction_to_child`, unaffected by the WS transport swap, but confirms `src/main.py` still imports cleanly)

- [ ] **Step 4: Sanity-check the module imports end-to-end**

Run: `.venv/bin/python3 -c "import src.main"`
Expected: no output, exit code 0 (confirms `WsServer`/`build_bind_address` wiring has no import errors)

- [ ] **Step 5: Commit**

```bash
git add src/main.py
git commit -m "feat: main.py hosts a WS server instead of dialing out to one"
```

---

### Task 6: `site/` — Express static server + package scaffolding

**Files:**
- Create: `site/package.json`
- Create: `site/server.js`
- Create: `site/public/index.html` (placeholder shell, filled in fully by Task 8)
- Test: `site/tests/server.test.js` (new)

**Interfaces:**
- Produces: `createApp() -> express.Express` (exported from `server.js`), used by Task 7's test and by the `require.main === module` startup block.

- [ ] **Step 1: Scaffold the package**

Create `site/package.json`:

```json
{
  "name": "gremlin-control-site",
  "version": "1.0.0",
  "private": true,
  "description": "Control website for the gremlin robot",
  "main": "server.js",
  "scripts": {
    "start": "node server.js",
    "test": "node --test tests/"
  },
  "dependencies": {
    "express": "^4.19.2",
    "ws": "^8.18.0"
  }
}
```

- [ ] **Step 2: Write the failing test**

Create `site/tests/server.test.js`:

```javascript
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const path = require('node:path');
const fs = require('node:fs');

const { createApp } = require('../server');

test('createApp serves the static index page', async () => {
  const publicDir = path.join(__dirname, '..', 'public');
  assert.ok(fs.existsSync(path.join(publicDir, 'index.html')), 'public/index.html must exist');

  const app = createApp();
  const server = http.createServer(app);

  await new Promise((resolve) => server.listen(0, resolve));
  const { port } = server.address();

  const body = await new Promise((resolve, reject) => {
    http.get(`http://127.0.0.1:${port}/`, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => resolve(data));
    }).on('error', reject);
  });

  assert.ok(body.includes('<'), 'expected HTML content from index page');

  await new Promise((resolve) => server.close(resolve));
});
```

- [ ] **Step 3: Run test to verify it fails**

Run (from `site/`): `npm install && npm test`
Expected: FAIL — `../server` module not found (or `createApp` undefined)

- [ ] **Step 4: Write minimal implementation**

Create `site/public/index.html` (minimal placeholder, replaced fully in Task 8):

```html
<!doctype html>
<html>
  <head><title>Gremlin Control</title></head>
  <body><h1>Gremlin Control</h1></body>
</html>
```

Create `site/server.js`:

```javascript
const express = require('express');
const path = require('path');

function createApp() {
  const app = express();
  app.use(express.static(path.join(__dirname, 'public')));
  return app;
}

module.exports = { createApp };

if (require.main === module) {
  const PORT = process.env.PORT || 3000;
  const app = createApp();
  app.listen(PORT, () => {
    console.log(`Control site listening on :${PORT}`);
  });
}
```

- [ ] **Step 5: Run test to verify it passes**

Run (from `site/`): `npm test`
Expected: pass 1

- [ ] **Step 6: Commit**

```bash
git add site/package.json site/server.js site/public/index.html site/tests/server.test.js
git commit -m "feat: scaffold Express control site with static file serving"
```

(`site/package-lock.json` and `site/node_modules/` will also be present after `npm install` — add a `site/.gitignore` with `node_modules/` before committing if one doesn't already exist at the repo root covering it.)

- [ ] **Step 7: Ensure node_modules is ignored**

Check the repo root `.gitignore` for a `node_modules/` entry:

Run: `grep -n node_modules .gitignore`

If it's missing, append it:

```bash
echo "node_modules/" >> .gitignore
git add .gitignore
git commit -m "chore: ignore node_modules"
```

---

### Task 7: `site/server.js` — UDP-to-WS video relay

**Files:**
- Modify: `site/server.js`
- Test: `site/tests/video_relay.test.js` (new)

**Interfaces:**
- Consumes: `ws` package's `WebSocketServer`, Node's built-in `dgram`.
- Produces: `createVideoRelay(udpPort: number) -> { wss: WebSocketServer, udpSocket: dgram.Socket }`, exported from `server.js`. `wss` is created with `{ noServer: true }` so the caller wires it to an HTTP server's `upgrade` event (done in the `require.main === module` block).

- [ ] **Step 1: Write the failing test**

Create `site/tests/video_relay.test.js`:

```javascript
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const dgram = require('node:dgram');
const WebSocket = require('ws');

const { createApp, createVideoRelay } = require('../server');

test('UDP datagrams are relayed to the connected video WS client', async () => {
  const app = createApp();
  const server = http.createServer(app);
  const { wss, udpSocket } = createVideoRelay(0);

  server.on('upgrade', (request, socket, head) => {
    if (request.url === '/video') {
      wss.handleUpgrade(request, socket, head, (ws) => {
        wss.emit('connection', ws, request);
      });
    } else {
      socket.destroy();
    }
  });

  await new Promise((resolve) => server.listen(0, resolve));
  const { port: httpPort } = server.address();
  const udpPort = udpSocket.address().port;

  const client = new WebSocket(`ws://127.0.0.1:${httpPort}/video`);
  await new Promise((resolve, reject) => {
    client.on('open', resolve);
    client.on('error', reject);
  });

  const received = new Promise((resolve) => {
    client.on('message', (data) => resolve(data));
  });

  const sender = dgram.createSocket('udp4');
  const payload = Buffer.from('fake-jpeg-frame-bytes');
  sender.send(payload, udpPort, '127.0.0.1');

  const message = await received;
  assert.deepEqual(Buffer.from(message), payload);

  sender.close();
  client.close();
  udpSocket.close();
  await new Promise((resolve) => server.close(resolve));
});

test('createVideoRelay drops datagrams when no client is connected', async () => {
  const { udpSocket } = createVideoRelay(0);
  const udpPort = udpSocket.address().port;

  const sender = dgram.createSocket('udp4');
  sender.send(Buffer.from('no-one-listening'), udpPort, '127.0.0.1');

  await new Promise((resolve) => setTimeout(resolve, 50));

  sender.close();
  udpSocket.close();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `site/`): `npm test`
Expected: FAIL — `createVideoRelay is not a function`

- [ ] **Step 3: Write minimal implementation**

Update `site/server.js` in full:

```javascript
const express = require('express');
const path = require('path');
const dgram = require('dgram');
const { WebSocketServer } = require('ws');

function createApp() {
  const app = express();
  app.use(express.static(path.join(__dirname, 'public')));
  return app;
}

function createVideoRelay(udpPort) {
  const wss = new WebSocketServer({ noServer: true });
  let browserSocket = null;

  wss.on('connection', (ws) => {
    browserSocket = ws;
    ws.on('close', () => {
      if (browserSocket === ws) {
        browserSocket = null;
      }
    });
  });

  const udpSocket = dgram.createSocket('udp4');
  udpSocket.on('message', (msg) => {
    if (browserSocket && browserSocket.readyState === browserSocket.OPEN) {
      browserSocket.send(msg);
    }
  });
  udpSocket.bind(udpPort);

  return { wss, udpSocket };
}

module.exports = { createApp, createVideoRelay };

if (require.main === module) {
  const PORT = process.env.PORT || 3000;
  const UDP_PORT = process.env.UDP_PORT || 9000;

  const app = createApp();
  const server = app.listen(PORT, () => {
    console.log(`Control site listening on :${PORT}`);
  });

  const { wss } = createVideoRelay(UDP_PORT);

  server.on('upgrade', (request, socket, head) => {
    if (request.url === '/video') {
      wss.handleUpgrade(request, socket, head, (ws) => {
        wss.emit('connection', ws, request);
      });
    } else {
      socket.destroy();
    }
  });

  console.log(`UDP video relay listening on :${UDP_PORT}`);
}
```

Note: `dgram.createSocket('udp4').bind(0)` picks an ephemeral port, which is why the test reads `udpSocket.address().port` back rather than hardcoding one — this lets multiple test files run concurrently without port clashes.

- [ ] **Step 4: Run test to verify it passes**

Run (from `site/`): `npm test`
Expected: pass 3 (the static-file test from Task 6 plus these two)

- [ ] **Step 5: Commit**

```bash
git add site/server.js site/tests/video_relay.test.js
git commit -m "feat: add UDP-to-WS video relay to the control site server"
```

---

### Task 8: Control page — IP form, connection indicator, control WS, video WS

This is the frontend piece; it has no automated test (no browser test runner is set up, and adding one is out of scope for this rewrite — the spec calls for manual browser verification instead). Final manual verification happens in Task 9.

**Files:**
- Modify: `site/public/index.html` (replace placeholder from Task 6)
- Create: `site/public/app.js`
- Create: `site/public/style.css`
- Modify: `site/server.js` (add a tiny `/api/config` JSON endpoint so the page knows which UDP port to tell the robot about)
- Test: `site/tests/config_endpoint.test.js` (new — this part *is* server-side and testable)

**Interfaces:**
- Consumes: `createApp()` from Task 6.
- Produces: `GET /api/config` → `{"udpPort": <number>}`, read by `app.js` on page load.

- [ ] **Step 1: Write the failing test for `/api/config`**

Create `site/tests/config_endpoint.test.js`:

```javascript
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');

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
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `site/`): `npm test`
Expected: FAIL — response body is HTML (or 404), not the expected JSON

- [ ] **Step 3: Update `createApp` to accept config and add the endpoint**

In `site/server.js`, change `createApp` to:

```javascript
function createApp(options = {}) {
  const udpPort = options.udpPort || Number(process.env.UDP_PORT) || 9000;

  const app = express();
  app.use(express.static(path.join(__dirname, 'public')));
  app.get('/api/config', (req, res) => {
    res.json({ udpPort });
  });
  return app;
}
```

And update the `require.main === module` block to pass it through:

```javascript
  const app = createApp({ udpPort: UDP_PORT });
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `site/`): `npm test`
Expected: pass 4

- [ ] **Step 5: Commit**

```bash
git add site/server.js site/tests/config_endpoint.test.js
git commit -m "feat: add /api/config endpoint exposing the video relay's UDP port"
```

- [ ] **Step 6: Write the control page HTML**

Replace `site/public/index.html` in full:

```html
<!doctype html>
<html lang="pl">
  <head>
    <meta charset="utf-8" />
    <title>Gremlin Control</title>
    <link rel="stylesheet" href="style.css" />
  </head>
  <body>
    <h1>Gremlin Control</h1>

    <form id="connect-form">
      <label for="robot-ip">IP robota</label>
      <input id="robot-ip" name="robot-ip" type="text" placeholder="192.168.1.162" required />
      <button type="submit">Połącz</button>
    </form>

    <div id="status" class="status status-disconnected">Rozłączony</div>

    <img id="video" alt="Podgląd kamery" />

    <script src="app.js"></script>
  </body>
</html>
```

- [ ] **Step 7: Write the control page styling**

Create `site/public/style.css`:

```css
body {
  font-family: sans-serif;
  max-width: 640px;
  margin: 2rem auto;
  padding: 0 1rem;
}

.status {
  display: inline-block;
  padding: 0.5rem 1rem;
  border-radius: 0.25rem;
  font-weight: bold;
  margin: 1rem 0;
}

.status-connecting {
  background: #eab308;
  color: #000;
}

.status-connected {
  background: #16a34a;
  color: #fff;
}

.status-disconnected {
  background: #dc2626;
  color: #fff;
}

#video {
  display: block;
  max-width: 100%;
  border: 1px solid #ccc;
  margin-top: 1rem;
}
```

- [ ] **Step 8: Write the control page logic**

Create `site/public/app.js`:

```javascript
const form = document.getElementById('connect-form');
const ipInput = document.getElementById('robot-ip');
const statusEl = document.getElementById('status');
const videoEl = document.getElementById('video');

let controlSocket = null;
let videoSocket = null;
let currentVideoUrl = null;

function setStatus(state) {
  const labels = {
    connecting: 'Łączenie...',
    connected: 'Połączony',
    disconnected: 'Rozłączony',
  };
  statusEl.textContent = labels[state] || labels.disconnected;
  statusEl.className = `status status-${state}`;
}

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

  controlSocket = new WebSocket(`ws://${robotIp}:8765`);

  controlSocket.onopen = () => {
    setStatus('connected');
    controlSocket.send(JSON.stringify({
      type: 'register_video_sink',
      host: window.location.hostname,
      port: udpPort,
    }));
  };

  controlSocket.onclose = () => setStatus('disconnected');
  controlSocket.onerror = () => setStatus('disconnected');
}

form.addEventListener('submit', (event) => {
  event.preventDefault();
  connect(ipInput.value.trim());
});
```

- [ ] **Step 9: Run the full site test suite once more to confirm nothing regressed**

Run (from `site/`): `npm test`
Expected: pass 4

- [ ] **Step 10: Commit**

```bash
git add site/public/index.html site/public/style.css site/public/app.js
git commit -m "feat: add control page UI (IP form, connection indicator, video relay wiring)"
```

---

### Task 9: End-to-end manual verification

This task has no automated steps — it requires the actual Raspberry Pi hardware (per `Global Constraints`, this rewrite touches the transport main.py depends on, which can only be fully verified against real GPIO/I2C/camera hardware). Do not claim this feature complete until these steps are actually run and observed.

- [ ] **Step 1: Run the full automated suites one last time**

```bash
.venv/bin/python3 -m pytest tests/ -v
```
Expected: all passed

```bash
cd site && npm test
```
Expected: all passed

- [ ] **Step 2: Start the site locally**

```bash
cd site && npm install && node server.js
```
Expected: logs `Control site listening on :3000` and `UDP video relay listening on :9000`

- [ ] **Step 3: Start `main.py` on the Raspberry Pi** (or a dev machine with `config.json`'s hardware sections set to `is_dummy: true`)

```bash
python3 -m src.main
```
Expected: no exceptions on startup; the process stays running (it's now waiting for an inbound WS connection instead of dialing out).

- [ ] **Step 4: Open the control page in a browser**

Navigate to `http://<site-host>:3000/`, type the robot's IP into the form, click "Połącz".

Expected:
- Status indicator turns green ("Połączony") within a couple seconds.
- Sending a command that reaches real hardware (e.g. toggling a GPIO pin exposed in the UI, once such a control exists — if the control page doesn't yet expose GPIO controls beyond connect/video, verify instead by opening a second manual WS client, e.g. `wscat -c ws://<robot-ip>:8765`, and sending `{"type":"set_program_status","status":"on"}`, confirming `program_manager` starts).
- If `oak_d.is_dummy` is `false` and real camera hardware is present, the `<img id="video">` element starts showing frames within a few seconds of the robot receiving `register_video_sink`.

- [ ] **Step 5: Verify single-connection replacement**

Open the control page in a second browser tab and connect to the same robot IP. Expected: the first tab's status flips to "Rozłączony" (its WS connection was closed server-side), the second tab shows "Połączony".

- [ ] **Step 6: Record results**

If everything above matches, the feature is complete. If any step fails, treat it as a bug against this plan — do not mark the task done, and go back to `systematic-debugging` for that specific failure rather than patching around it here.
