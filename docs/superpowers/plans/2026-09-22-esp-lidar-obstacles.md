# ESP LiDAR Obstacles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Receive ESP LiDAR type-3 obstacle datagrams and render the newest obstacle bounding boxes as red, semi-transparent 3D boxes in the ESP LiDAR tab.

**Architecture:** Extend the ESP UDP parser with typed obstacle packets, assemble packets by source frame in `EspLidarService`, and reuse the existing WebSocket obstacle encoding and browser decoder. Add an obstacle group to the ESP Three.js viewer and apply the same ESP-to-Three axis remap and orientation transforms as the point cloud.

**Tech Stack:** Python 3, `struct`, `pytest`, browser JavaScript, Three.js, Node.js `node:test`.

## Global Constraints

- Use the 32-byte little-endian LIDR header and 32-byte obstacle records defined in `esp_rasp_test/PROTOCOL.txt`.
- Preserve the existing point-cloud and IMU protocols and the existing Unitree LiDAR tab.
- A valid zero-obstacle frame must clear stale obstacle boxes.
- Malformed UDP packets must be ignored without stopping the service.
- Do not modify ESP firmware or obstacle-detection thresholds.

---

### Task 1: Decode ESP obstacle datagrams

**Files:**
- Modify: `backend/esp_lidar/frame_parser.py`
- Create: `tests/test_esp_lidar_frame_parser.py`

**Interfaces:** Add `MSG_OBSTACLES = 3`, `ObstacleRecord`, `ObstaclePacket`, and extend `decode_packet(data)` to return `ObstaclePacket` for type 3. The record fields are the seven float32 values followed by `point_count` and `flags`; the packet also carries frame, packet, total-count, and timestamp fields.

- [ ] **Step 1: Write failing parser tests**

Build real datagrams with `struct.pack("<4sBBHIHHHHQI", ...)` and `struct.pack("<7fHH", ...)`. Cover one valid record, a valid zero-obstacle frame, a truncated record raising `FrameParseError`, and `packet_count == 0` raising `FrameParseError`.

```python
def test_decode_obstacle_packet():
    data = make_obstacle_datagram(17, 0, 1, 1, [(1.0, 2.0, 0.5, 0.4, 0.6, 1.2, 1.1, 12, 3)])
    packet = decode_packet(data)
    assert packet.frame_id == 17
    assert packet.obstacles[0].center_x == 1.0
    assert packet.obstacles[0].size_z == 1.2

def test_decode_empty_obstacle_frame():
    packet = decode_packet(make_obstacle_datagram(18, 0, 1, 0, []))
    assert isinstance(packet, ObstaclePacket)
    assert packet.obstacles == []

def test_decode_obstacle_packet_rejects_bad_datagrams():
    with pytest.raises(FrameParseError):
        decode_packet(make_obstacle_datagram(19, 0, 1, 1, [], truncate=True))
    with pytest.raises(FrameParseError):
        decode_packet(make_obstacle_datagram(20, 0, 0, 0, []))
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `pytest -q tests/test_esp_lidar_frame_parser.py`

Expected: FAIL because type 3 is not decoded and `ObstaclePacket` is absent.

- [ ] **Step 3: Implement the minimal type-3 parser**

Add `_OBSTACLE_FMT = "<7fHH"` and `_OBSTACLE_LEN = struct.calcsize(_OBSTACLE_FMT)`. Read `field_18` as `total_obstacle_count`, require `packet_count > 0`, require `len(data) >= 32 + field_16 * 32`, unpack every record, and return `ObstaclePacket`. Keep unknown types returning `None` and preserve type-1/type-2 behavior.

- [ ] **Step 4: Run parser tests and regression tests**

Run: `pytest -q tests/test_esp_lidar_frame_parser.py tests/test_frame_parser.py`

Expected: PASS.

- [ ] **Step 5: Commit the parser slice**

```bash
git add backend/esp_lidar/frame_parser.py tests/test_esp_lidar_frame_parser.py
git commit -m "feat: decode ESP LiDAR obstacle packets"
```

### Task 2: Assemble obstacle frames and broadcast them

**Files:**
- Modify: `backend/esp_lidar/http_api.py`
- Create: `tests/test_esp_lidar_obstacles.py`

**Interfaces:** Add an obstacle packet accumulator keyed by `frame_id`. Emit `encode_obstacles_frame(records)` only after all `packet_count` datagrams arrive, and emit an empty obstacle frame for a valid zero-obstacle source frame. Reuse `backend.lidar.ws_server.encode_obstacles_frame` and its existing obstacle record shape.

- [ ] **Step 1: Write failing service tests**

```python
def test_obstacle_packets_wait_for_complete_frame():
    service = EspLidarService(broadcast_interval=0.01)
    service.handle_datagram(make_obstacle_datagram(7, 0, 2, 2, [obstacle(1.0)]))
    assert service.latest_obstacles is None
    service.handle_datagram(make_obstacle_datagram(7, 1, 2, 2, [obstacle(2.0)]))
    assert [item.center_x for item in service.latest_obstacles] == [1.0, 2.0]

def test_empty_obstacle_frame_clears_latest_obstacles():
    service = EspLidarService(broadcast_interval=0.01)
    service.latest_obstacles = [obstacle(1.0)]
    service.handle_datagram(make_obstacle_datagram(8, 0, 1, 0, []))
    assert service.latest_obstacles == []
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `pytest -q tests/test_esp_lidar_obstacles.py`

Expected: FAIL because `EspLidarService` does not handle `ObstaclePacket`.

- [ ] **Step 3: Implement frame assembly**

Track frame ID, expected packet count, packet records, and source timestamp. Ignore duplicate packet IDs and discard an in-progress frame when a newer frame supersedes it. On completion, sort records by packet ID, set `latest_obstacles`, and let the broadcast loop send the existing WS type-3 frame. Reset the list on a valid zero-obstacle frame. Do not change point-cloud accumulation.

- [ ] **Step 4: Run backend tests**

Run: `pytest -q tests/test_esp_lidar_obstacles.py tests/test_esp_lidar_frame_parser.py tests/test_esp_lidar_accumulator.py`

Expected: PASS.

- [ ] **Step 5: Commit the backend slice**

```bash
git add backend/esp_lidar/http_api.py tests/test_esp_lidar_obstacles.py
git commit -m "feat: broadcast ESP LiDAR obstacles"
```

### Task 3: Render ESP obstacle boxes

**Files:**
- Modify: `site/public/esp_lidar/js/viewer.js`
- Modify: `site/public/tabs/esp-lidar.js`
- Create: `site/tests/esp-lidar-obstacles.test.js`

**Interfaces:** Add `viewer.setObstacles(obstacles)` and an `onObstacles` WebSocket callback. Keep obstacle meshes under one group that receives the same remapped coordinates and quaternion as the point cloud.

- [ ] **Step 1: Write failing frontend tests**

```javascript
test('ESP obstacle layer creates a red transformed box', () => {
    const layer = createEspObstacleLayer(makeFakeThree());
    layer.setObstacles([{ centerX: 1, centerY: 2, centerZ: 3,
        sizeX: 4, sizeY: 5, sizeZ: 6 }]);
    assert.equal(layer.group.children.length, 1);
    assert.equal(layer.group.children[0].material.color, 0xff2020);
    assert.deepEqual(layer.group.children[0].position, { x: -1, y: 3, z: 2 });
    assert.deepEqual(layer.group.children[0].scale, { x: 4, y: 6, z: 5 });
});

test('ESP obstacle layer clears on an empty frame', () => {
    const layer = createEspObstacleLayer(makeFakeThree());
    layer.setObstacles([{ centerX: 1, centerY: 2, centerZ: 3,
        sizeX: 1, sizeY: 1, sizeZ: 1 }]);
    layer.setObstacles([]);
    assert.equal(layer.group.children.length, 0);
});
```

- [ ] **Step 2: Run the focused frontend test and verify it fails**

Run: `node --test site/tests/esp-lidar-obstacles.test.js`

Expected: FAIL because the obstacle layer does not exist.

- [ ] **Step 3: Implement the obstacle group**

Create box geometry and a red `MeshBasicMaterial` with `transparent: true`, opacity around `0.35`, and depth writing disabled. Map ESP center `(x, y, z)` to Three `(-x, z, y)` and dimensions `(size_x, size_z, size_y)`. Replace old children on every update, reject non-finite or non-positive dimensions, and expose `setObstacles` from `createEspViewer`.

- [ ] **Step 4: Apply orientation to both layers**

Put the obstacle group in the same transformed scene object as the point cloud, or apply the same quaternion whenever `applyEspFrameQuaternion` and `setManualTilt` update the cloud. Points and boxes must rotate together without changing the existing point-cloud mapping.

- [ ] **Step 5: Connect WS obstacle callbacks**

In `site/public/tabs/esp-lidar.js`, add `onObstacles: ({ obstacles }) => viewer.setObstacles(obstacles)`. Keep scan, IMU, connection status, and metrics callbacks unchanged.

- [ ] **Step 6: Run frontend tests**

Run: `node --test site/tests/esp-lidar-obstacles.test.js site/tests/esp-lidar-pointcloud.test.js site/tests/lidar-frontend.test.js`

Expected: PASS.

- [ ] **Step 7: Commit the frontend slice**

```bash
git add site/public/esp_lidar/js/viewer.js site/public/tabs/esp-lidar.js site/tests/esp-lidar-obstacles.test.js
git commit -m "feat: show ESP LiDAR obstacles as red boxes"
```

### Task 4: Validate the complete integration

- [ ] **Step 1: Run all ESP LiDAR backend tests**

Run: `pytest -q tests/test_esp_lidar_frame_parser.py tests/test_esp_lidar_obstacles.py tests/test_esp_lidar_accumulator.py`

Expected: PASS.

- [ ] **Step 2: Run all related frontend tests**

Run: `node --test site/tests/esp-lidar-obstacles.test.js site/tests/esp-lidar-pointcloud.test.js site/tests/lidar-frontend.test.js`

Expected: PASS.

- [ ] **Step 3: Run LiDAR regression tests**

Run: `pytest -q tests/test_lidar_startup.py tests/test_frame_parser.py tests/test_esp_lidar_accumulator.py`

Expected: PASS with no regressions in existing LiDAR startup or parser behavior.

- [ ] **Step 4: Review the final diff and service status**

Run: `git diff HEAD~3..HEAD --stat && git status --short`

Expected: only planned parser, service, viewer, tests, and documentation files are changed; unrelated pre-existing worktree changes remain untouched.