# ESP LiDAR UDP Forwarding Implementation Plan

**Goal:** Forward completed ESP LiDAR scan frames from Raspberry Pi to a configurable UDP destination and document reassembly/decoding for Node.js.

**Architecture:** Add an optional UDP forwarder to the existing ESP LiDAR service. It fragments point records into MTU-friendly datagrams with a small metadata header; joining chunk payloads recreates the exact existing WebSocket scan frame (`uint32 type`, `uint32 point count`, then four float32 values per point). Configure destination in `config.json`; an empty host disables forwarding.

**Tech Stack:** Python 3 asyncio service, UDP sockets, pytest, Node.js `dgram` decoder example in Markdown.

## Global Constraints

- Do not alter the existing WebSocket protocol or ESP-to-Pi input protocol.
- Forward only complete point-cloud snapshots, not IMU or obstacle messages.
- UDP delivery is best-effort; incomplete frames must be discarded by consumers.
- Preserve all existing user changes in `config.json`.

---

### Task 1: UDP packet encoder and sender

**Files:** Create `backend/esp_lidar/udp_forwarder.py`; create `tests/test_esp_lidar_udp_forwarder.py`.

**Interfaces:** `encode_scan_datagrams(frame_id, points, max_datagram_size=1400)` returns ordered datagrams. `PointCloudUdpForwarder(host, port, max_datagram_size=1400).send_frame(frame_id, points)` sends those datagrams to the configured destination and `close()` closes the socket.

- [ ] Test one-fragment payload, multi-fragment payload, empty scan, and invalid datagram size.
- [ ] Verify tests fail before implementation.
- [ ] Implement a 20-byte little-endian header (`ELDP`, version, type, header size, frame ID, chunk index/count, total point count), then little-endian float32 point payloads.
- [ ] Run the focused test module.

### Task 2: Service integration and configuration

**Files:** Modify `backend/esp_lidar/http_api.py`, `backend/esp_lidar/accumulator.py`, `src/main.py`, and `config.json`; create/extend focused service tests.

- [ ] Add optional destination host, UDP port, and maximum datagram size settings; no configured host means no forwarding socket.
- [ ] Send each point-cloud snapshot alongside the existing WebSocket scan broadcast, including the one-time empty scan used to clear a stale display.
- [ ] Close the forwarding socket during service cleanup.
- [ ] Verify existing WebSocket behavior and forwarding with focused tests.

### Task 3: Decoder documentation

**Files:** Create `docs/ESP_LIDAR_UDP_FORWARDING.md`.

- [ ] Document configuration, transport reliability, exact header offsets, point layout, reconstruction of the existing WebSocket scan frame, and a minimal Node.js `dgram` receiver/reassembly example.
- [ ] State that the receiver must be reachable over the network and that UDP/firewall rules must allow the destination port.

### Task 4: Validation

- [ ] Run focused ESP LiDAR tests.
- [ ] Run the complete Python test suite if runtime permits.
- [ ] Inspect the final diff and report exact configuration keys and verification results.
