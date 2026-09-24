# ESP LiDAR Web Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add complete `CONTROL_PROTOCOL` control of the ESP32-P4 to the existing ESP LiDAR web tab.

**Architecture:** A focused Python UDP client will own binary frame encoding, ACK validation, retries, and decoded state. The aiohttp service will expose command and status HTTP endpoints, while the existing browser tab will render controls and apply state returned by ACKs.

**Tech Stack:** Python 3, asyncio/aiohttp, UDP sockets, browser Fetch API, vanilla JavaScript, pytest, Node test runner.

## Global Constraints

- Preserve the 32-byte little-endian LIDR v1 header and 16-byte command/ACK payloads.
- Use control destination `192.168.50.10:5006` by default.
- Keep existing ESP LiDAR WebSocket streams unchanged.
- Return HTTP 400 for invalid requests and HTTP 502 for ESP transport failures.
- Do not modify unrelated existing worktree changes.

---

### Task 1: Implement the protocol client

**Files:**
- Create: `backend/esp_lidar/control.py`
- Create: `tests/test_esp_lidar_control.py`

**Interfaces:**
- Produces `EspControlClient.send(command_id: int, args: tuple[int, ...]) -> dict`.
- Produces `encode_command(request_id: int, command_id: int, args: Iterable[int]) -> bytes`.
- Produces `decode_ack(data: bytes, expected_request_id: int) -> dict | None`.

- [ ] **Step 1: Write failing protocol tests**

```python
def test_encode_command_matches_control_protocol():
    packet = encode_command(0x10203040, 3, (1,))
    assert len(packet) == 48
    assert packet[:4] == b"LIDR"
    assert struct.unpack_from("<BBH", packet, 4) == (1, 128, 32)
    assert struct.unpack_from("<IHHHHQI", packet, 8) == (
        0x10203040, 3, 0, 16, 0, 0, 0
    )
    assert struct.unpack_from("<IIII", packet, 32) == (1, 0, 0, 0)


def test_decode_ack_rejects_wrong_request_id():
    packet = make_ack(request_id=7, command_id=2, result=0,
                      state_flags=3, stream_mask=7,
                      command_count=9, uptime_ms=100)
    assert decode_ack(packet, expected_request_id=8) is None


def test_client_retries_and_returns_decoded_ack(fake_socket):
    client = EspControlClient("esp", 5006, socket_factory=fake_socket)
    result = client.send(2, ())
    assert result["result"] == 0
    assert fake_socket.send_count == 2
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `pytest -q tests/test_esp_lidar_control.py`
Expected: FAIL because `backend.esp_lidar.control` does not exist.

- [ ] **Step 3: Implement constants, frame functions, and client**

Use `struct.Struct("<4sBBHIHHHHQI")`, `struct.Struct("<IIII")`, monotonic/random request IDs, a one-second receive deadline, and three attempts. Ignore ACKs from another address or with a different request ID. Raise `TimeoutError` after all attempts. Decode the four ACK payload fields into `state_flags`, `stream_mask`, `command_count`, and `uptime_ms`, plus booleans `lidar_active` and `fusion_enabled`.

- [ ] **Step 4: Run focused tests**

Run: `pytest -q tests/test_esp_lidar_control.py`
Expected: PASS.

- [ ] **Step 5: Commit the protocol unit**

```bash
git add backend/esp_lidar/control.py tests/test_esp_lidar_control.py
git commit -m "feat: add ESP LiDAR control protocol client"
```

### Task 2: Add aiohttp control endpoints

**Files:**
- Modify: `backend/esp_lidar/http_api.py`
- Modify: `tests/test_esp_lidar_control.py`

**Interfaces:**
- `POST /api/esp_lidar/command` accepts `{"command": "set_lidar_active", "args": [1]}` and returns decoded ACK JSON.
- `GET /api/esp_lidar/status` sends command `GET_STATUS` and returns decoded ACK JSON.
- Service configuration accepts `--esp-ip` and `--control-port`.

- [ ] **Step 1: Add failing aiohttp endpoint tests**

Test that a valid command maps command names to IDs and returns a fake ACK, an unknown command returns 400, malformed arguments return 400, and a client timeout returns 502. Use an injected fake control client on `app["control_client"]` so no real UDP packet is sent.

- [ ] **Step 2: Run endpoint tests to verify failure**

Run: `pytest -q tests/test_esp_lidar_control.py -k endpoint`
Expected: FAIL because routes and control-client injection do not exist.

- [ ] **Step 3: Add command mapping and handlers**

Add IDs 1 through 9 with names `ping`, `get_status`, `set_lidar_active`, `set_stream_mask`, `set_fusion_active`, `clear_history`, `set_cloud_active`, `set_imu_active`, and `set_obstacles_active`. Validate integer arguments, require zero arguments for `ping`, `get_status`, and `clear_history`, and require one argument in the range 0..1 for boolean commands or 0..7 for stream masks. Return 400 for validation errors and 502 for `TimeoutError`/`OSError`.

- [ ] **Step 4: Add parser options and CORS methods**

Add `--esp-ip` defaulting to `192.168.50.10`, `--control-port` defaulting to `5006`, create the control client at startup, and allow `POST` in `Access-Control-Allow-Methods`.

- [ ] **Step 5: Run backend tests**

Run: `pytest -q tests/test_esp_lidar_control.py`
Expected: PASS.

- [ ] **Step 6: Commit backend endpoints**

```bash
git add backend/esp_lidar/http_api.py tests/test_esp_lidar_control.py
git commit -m "feat: expose ESP LiDAR control API"
```

### Task 3: Add the ESP LiDAR control panel

**Files:**
- Modify: `site/public/index.html`
- Modify: `site/public/tabs/esp-lidar.js`
- Create: `site/tests/esp-lidar-control.test.js`

**Interfaces:**
- Browser calls `${espServiceOrigin}/api/esp_lidar/command` and `/status`, using the existing page host and port `8769`.
- `applyAck(ack)` updates all visible controls from the returned ACK.

- [ ] **Step 1: Add failing static contract tests**

```js
test('ESP LiDAR tab exposes protocol controls', () => {
  const html = fs.readFileSync(path.join(publicDir, 'index.html'), 'utf8');
  const tab = fs.readFileSync(path.join(publicDir, 'tabs', 'esp-lidar.js'), 'utf8');
  assert.match(html, /esp-lidar-control/);
  assert.match(html, /esp-lidar-stream-mask/);
  assert.match(tab, /api\/esp_lidar\/command/);
  assert.match(tab, /set_stream_mask/);
  assert.match(tab, /clear_history/);
});
```

- [ ] **Step 2: Run the focused Node test and verify failure**

Run: `node --test site/tests/esp-lidar-control.test.js`
Expected: FAIL because the controls and endpoint calls do not exist.

- [ ] **Step 3: Add semantic control markup**

Add a control section with status text, buttons for ping/status/clear-history, checkboxes for LiDAR/fusion/cloud/IMU/obstacles, and a select for `all`, `none`, `cloud`, `imu`, `obstacles`, and supported combinations. Keep stable IDs and accessible labels.

- [ ] **Step 4: Implement fetch-based command actions**

Add command constants, `sendCommand(command, args)`, `refreshStatus()`, `applyAck(ack)`, pending-state disabling, result-code text, and error rendering. Each checkbox sends its corresponding command; the stream selector sends `set_stream_mask`. Refresh status when the tab initializes and after every successful command.

- [ ] **Step 5: Run frontend tests**

Run: `node --test site/tests/esp-lidar-control.test.js site/tests/esp-lidar-obstacles.test.js site/tests/esp-lidar-pointcloud.test.js`
Expected: PASS.

- [ ] **Step 6: Commit the web panel**

```bash
git add site/public/index.html site/public/tabs/esp-lidar.js site/tests/esp-lidar-control.test.js
git commit -m "feat: add ESP LiDAR web controls"
```

### Task 4: Run the complete focused verification

**Files:**
- Modify: none

- [ ] **Step 1: Run Python ESP LiDAR tests**

Run: `pytest -q tests/test_esp_lidar_control.py tests/test_esp_lidar_frame_parser.py tests/test_esp_lidar_accumulator.py tests/test_esp_lidar_obstacles.py`
Expected: PASS.

- [ ] **Step 2: Run site tests**

Run: `node --test site/tests/*.test.js`
Expected: PASS.

- [ ] **Step 3: Run static error checks**

Run: `python -m compileall -q backend/esp_lidar`
Expected: exit code 0.

- [ ] **Step 4: Inspect final diff and working tree**

Run: `git diff HEAD~3 --stat` and `git status --short`. Confirm only the control feature commits and pre-existing user changes are present; do not revert unrelated changes.