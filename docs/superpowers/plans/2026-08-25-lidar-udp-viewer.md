# Standalone UDP LiDAR Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone (non-ROS) Python + vanilla-JS application that
receives Unitree LiDAR L1 point cloud + IMU data over UDP (via the official
`unilidar_publisher_udp` bridge), streams it live to a browser over
WebSocket, renders it in Three.js, and supports recording/replaying
sessions for testing without hardware. This replaces the MAVLink/serial
lidar pipeline currently in the `gremlin` project.

**Architecture:** One Python `asyncio` process spawns and supervises the
`unilidar_publisher_udp` bridge subprocess, listens for its UDP datagrams,
parses Scan(102)/IMU(101) frames, accumulates points in a time-windowed
ring buffer with range filtering, and broadcasts binary frames to WebSocket
clients on a fixed cadence. A vanilla-JS frontend (Three.js vendored
locally, no CDN) decodes those frames and live-updates a `BufferGeometry`
in place. A `--replay` mode substitutes a recorded file for the live UDP
source, reusing the same parsing/broadcast pipeline.

**Tech Stack:** Python 3.13, `asyncio`, `websockets` (already used
elsewhere in `gremlin`, v16 API — single-argument `async def
handler(websocket)`), `struct` for binary framing, vanilla JS + Three.js
r128 (vendored locally). `rosbags` (pure-Python, no ROS install) for the
one-time `.bag` conversion tool only.

**Spec:** `docs/superpowers/specs/2026-08-25-lidar-udp-viewer-design.md`

## Global Constraints

- No ROS installation required for the app itself (`rosbags` — pure
  Python — is the only ROS-adjacent dependency, and only for the one-time
  `tools/convert_bag.py` script, never imported by the running app).
- No CDN dependencies at runtime — Three.js is vendored into the repo and
  served locally; the previous prototype broke because of a 404 on a
  CDN-hosted `OrbitControls.js`.
- Camera controls are a small custom spherical-orbit implementation — no
  `OrbitControls` import.
- Binary wire format for WebSocket messages (defined in Task 7) — all
  multi-byte fields little-endian, all float payloads start at a 4-byte
  boundary from the start of the message (this is a real constraint:
  `Float32Array` views throw `RangeError` if the byte offset isn't a
  multiple of 4 — the header layouts below are deliberately sized to
  satisfy this).
- Point color is derived from `intensity`, never from height/Z — the
  previous prototype's height-based coloring was misleading.
- Fail fast and loudly on setup errors (missing bridge binary, unreadable
  recording file) — no silent "no data" states masquerading as success.

---

## File Structure

```
gremlin/lidar_viewer/
  backend/
    __init__.py
    frame_parser.py       # ImuFrame/ScanFrame dataclasses + UDP payload parsing
    accumulator.py         # PointAccumulator: time-windowed ring buffer + range filter
    recorder.py             # FrameRecorder: append raw UDP datagrams to a file
    player.py                # read_records()/FramePlayer: replay a recording with original timing
    bridge_manager.py       # subprocess lifecycle for unilidar_publisher_udp
    udp_listener.py         # asyncio UDP DatagramProtocol
    ws_server.py             # binary/JSON frame encoders + ClientRegistry broadcast
    app.py                     # CLI entrypoint, wires everything together
  frontend/
    index.html
    css/style.css
    js/
      vendor/three.min.js     # vendored Three.js r128, committed to the repo
      color.js                  # pure intensity->RGB mapping (unit-testable without a DOM)
      ws_client.js             # binary/JSON WS decode (unit-testable without a DOM)
      pointcloud.js             # BufferGeometry live-update wrapper
      viewer.js                  # scene/camera/custom orbit controls/render loop
      imu_panel.js               # IMU text readout
      metrics_panel.js           # point count / FPS / latency readout
      main.js                     # wires the above together on page load
  tools/
    convert_bag.py           # one-time .bag -> recording-format converter (uses rosbags)
    requirements.txt          # rosbags (only needed to run this one script)
  tests/
    test_frame_parser.py
    test_accumulator.py
    test_recorder_player.py
    test_bridge_manager.py
    test_udp_listener.py
    test_ws_server.py
    test_app_replay_smoke.py
    test_convert_bag.py
    js/
      test_color.js            # run with plain `node`, no framework
      test_ws_client.js         # run with plain `node`, no framework
  requirements.txt          # websockets
  README.md
```

Files that change together live together: each backend module owns its
struct format constants and its own tests; the frontend's pure-logic
pieces (`color.js`, `ws_client.js`) are separated from DOM-touching pieces
(`viewer.js`, `pointcloud.js`, `*_panel.js`) specifically so the former can
be unit tested with plain `node` in this environment (no browser
available here) while the latter get a documented manual-verification
step.

---

## Task 1: Project scaffold

**Files:**
- Create: `gremlin/lidar_viewer/backend/__init__.py` (empty)
- Create: `gremlin/lidar_viewer/requirements.txt`
- Create: `gremlin/lidar_viewer/tests/__init__.py` (empty)
- Create: `gremlin/lidar_viewer/README.md`

**Interfaces:** none (no code yet) — this task just creates the directory
skeleton and dependency manifest that every later task assumes exists.

- [ ] **Step 1: Create the directory skeleton and empty package markers**

```bash
mkdir -p /home/gremlin/gremlin/lidar_viewer/backend
mkdir -p /home/gremlin/gremlin/lidar_viewer/frontend/js/vendor
mkdir -p /home/gremlin/gremlin/lidar_viewer/frontend/css
mkdir -p /home/gremlin/gremlin/lidar_viewer/tools
mkdir -p /home/gremlin/gremlin/lidar_viewer/tests/js
touch /home/gremlin/gremlin/lidar_viewer/backend/__init__.py
touch /home/gremlin/gremlin/lidar_viewer/tests/__init__.py
```

- [ ] **Step 2: Write `requirements.txt`**

```
websockets>=16.0
```

- [ ] **Step 3: Write `tools/requirements.txt`**

```
rosbags>=0.9
```

- [ ] **Step 4: Write a minimal `README.md`**

```markdown
# LiDAR Viewer (Unitree L1, UDP, standalone)

Samodzielna aplikacja do podgladu na zywo i odtwarzania nagran danych z
Unitree LiDAR L1. Zastepuje dotychczasowa sekcje LiDAR w `gremlin`.

## Wymagania

- Zbudowany bridge `unilidar_publisher_udp` z `unilidar_sdk`
  (`unilidar_sdk/unitree_lidar_sdk/build/bin/unilidar_publisher_udp` po
  zbudowaniu SDK).
- `pip install -r requirements.txt`

## Uzycie

Tryb live:
```
python3 -m backend.app --serial-port /dev/ttyUSB0 --bridge-path <sciezka_do_binarki>
```

Nagrywanie sesji live:
```
python3 -m backend.app --serial-port /dev/ttyUSB0 --bridge-path <sciezka> --record nagranie.bin
```

Odtwarzanie nagrania (bez sprzetu):
```
python3 -m backend.app --replay nagranie.bin
```

Nastepnie otworz `frontend/index.html` w przegladarce (serwowane przez
backend na porcie WS, patrz `--ws-port`).

## Konwersja istniejacego .bag

```
pip install -r tools/requirements.txt
python3 tools/convert_bag.py wejscie.bag wyjscie.bin
```
```

- [ ] **Step 5: Commit**

```bash
cd /home/gremlin/gremlin
git add lidar_viewer/
git commit -m "scaffold: standalone lidar_viewer project skeleton"
```

---

## Task 2: `frame_parser.py` — UDP payload parsing

**Files:**
- Create: `gremlin/lidar_viewer/backend/frame_parser.py`
- Test: `gremlin/lidar_viewer/tests/test_frame_parser.py`

**Interfaces:**
- Produces: `ImuFrame(stamp: float, id: int, quaternion: tuple[float,float,float,float], angular_velocity: tuple[float,float,float], linear_acceleration: tuple[float,float,float])`
- Produces: `ScanFrame(stamp: float, id: int, points: list[tuple[float,float,float,float,float,int]])` — each point tuple is `(x, y, z, intensity, time, ring)`
- Produces: `FrameParseError(ValueError)` exception
- Produces: `parse_udp_datagram(data: bytes) -> ImuFrame | ScanFrame | None` — `None` for unknown `msgType`
- Produces: constants `IMU_MSG_TYPE = 101`, `SCAN_MSG_TYPE = 102`, `POINTS_PER_SCAN = 120`

This is pure logic, no I/O — every later backend task that touches parsed
data imports from here.

- [ ] **Step 1: Write the failing tests**

```python
# gremlin/lidar_viewer/tests/test_frame_parser.py
import struct

import pytest

from backend.frame_parser import (
    FrameParseError,
    ImuFrame,
    IMU_MSG_TYPE,
    POINTS_PER_SCAN,
    ScanFrame,
    SCAN_MSG_TYPE,
    parse_udp_datagram,
)

_HEADER_FMT = "<II"
_IMU_FMT = "<dI4f3f3f"
_POINT_FMT = "<fffffI"
_SCAN_PREFIX_FMT = "<dII"


def _build_datagram(msg_type: int, payload: bytes) -> bytes:
    header = struct.pack(_HEADER_FMT, msg_type, len(payload))
    return header + payload


def test_parse_imu_frame():
    quaternion = (0.0, 0.0, 0.0, 1.0)
    angular_velocity = (0.1, -0.2, 0.3)
    linear_acceleration = (0.0, 0.0, 9.81)
    payload = struct.pack(_IMU_FMT, 123.5, 7, *quaternion, *angular_velocity, *linear_acceleration)
    datagram = _build_datagram(IMU_MSG_TYPE, payload)

    frame = parse_udp_datagram(datagram)

    assert isinstance(frame, ImuFrame)
    assert frame.id == 7
    assert frame.stamp == pytest.approx(123.5)
    assert frame.quaternion == pytest.approx(quaternion)
    assert frame.angular_velocity == pytest.approx(angular_velocity)
    assert frame.linear_acceleration == pytest.approx(linear_acceleration)


def test_parse_scan_frame_uses_only_valid_points():
    valid_points_num = 3
    all_points = [(float(i), float(i) * 2, 0.5, 100.0 + i, 0.001 * i, i) for i in range(POINTS_PER_SCAN)]
    points_bytes = b"".join(struct.pack(_POINT_FMT, *p) for p in all_points)
    payload = struct.pack(_SCAN_PREFIX_FMT, 42.0, 9, valid_points_num) + points_bytes
    datagram = _build_datagram(SCAN_MSG_TYPE, payload)

    frame = parse_udp_datagram(datagram)

    assert isinstance(frame, ScanFrame)
    assert frame.id == 9
    assert frame.stamp == pytest.approx(42.0)
    assert len(frame.points) == valid_points_num
    assert frame.points[0] == pytest.approx(all_points[0])
    assert frame.points[2] == pytest.approx(all_points[2])


def test_parse_unknown_msg_type_returns_none():
    datagram = _build_datagram(999, b"\x00" * 4)
    assert parse_udp_datagram(datagram) is None


def test_parse_datagram_too_short_for_header_raises():
    with pytest.raises(FrameParseError):
        parse_udp_datagram(b"\x01\x02\x03")


def test_parse_imu_payload_shorter_than_declared_length_raises():
    header = struct.pack(_HEADER_FMT, IMU_MSG_TYPE, 999)
    with pytest.raises(FrameParseError):
        parse_udp_datagram(header + b"\x00" * 4)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/gremlin/gremlin/lidar_viewer && python3 -m pytest tests/test_frame_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.frame_parser'` (or `ImportError`).

- [ ] **Step 3: Implement `frame_parser.py`**

```python
# gremlin/lidar_viewer/backend/frame_parser.py
"""
Parsowanie ramek UDP z bridge'a unilidar_publisher_udp (SDK Unitree).

Format kazdego datagramu: naglowek msgType(uint32)+length(uint32), potem
payload. msgType==101 -> IMU, msgType==102 -> Scan (do 120 punktow, tylko
pierwsze validPointsNum jest znaczace - reszta stalej tablicy 120-elementowej
to nieistotne dane, ale bridge zawsze wysyla caly stale-rozmiarowy struct).

Wszystkie formaty zweryfikowane wprost wg oficjalnego przykladu Unitree
(unilidar_subcriber_udp.py) i struktur C++ (PointUnitree, ScanUnitree,
IMUUnitree) w unilidar_sdk.
"""

import struct
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

IMU_MSG_TYPE = 101
SCAN_MSG_TYPE = 102
POINTS_PER_SCAN = 120

_HEADER_FMT = "<II"
_HEADER_LEN = struct.calcsize(_HEADER_FMT)

_IMU_FMT = "<dI4f3f3f"
_IMU_LEN = struct.calcsize(_IMU_FMT)

_POINT_FMT = "<fffffI"
_POINT_LEN = struct.calcsize(_POINT_FMT)

_SCAN_PREFIX_FMT = "<dII"
_SCAN_PREFIX_LEN = struct.calcsize(_SCAN_PREFIX_FMT)
_SCAN_PAYLOAD_LEN = _SCAN_PREFIX_LEN + POINTS_PER_SCAN * _POINT_LEN


class FrameParseError(ValueError):
    """Ramka uszkodzona lub za krotka do sparsowania."""


@dataclass
class ImuFrame:
    stamp: float
    id: int
    quaternion: Tuple[float, float, float, float]
    angular_velocity: Tuple[float, float, float]
    linear_acceleration: Tuple[float, float, float]


@dataclass
class ScanFrame:
    stamp: float
    id: int
    points: List[Tuple[float, float, float, float, float, int]]  # x,y,z,intensity,time,ring


def parse_udp_datagram(data: bytes) -> Optional[Union[ImuFrame, ScanFrame]]:
    if len(data) < _HEADER_LEN:
        raise FrameParseError(f"datagram too short for header: {len(data)} bytes")

    msg_type, length = struct.unpack(_HEADER_FMT, data[:_HEADER_LEN])
    payload = data[_HEADER_LEN:_HEADER_LEN + length]
    if len(payload) < length:
        raise FrameParseError(
            f"declared length {length} exceeds available {len(payload)} bytes"
        )

    if msg_type == IMU_MSG_TYPE:
        return _parse_imu(payload)
    if msg_type == SCAN_MSG_TYPE:
        return _parse_scan(payload)
    return None


def _parse_imu(payload: bytes) -> ImuFrame:
    if len(payload) < _IMU_LEN:
        raise FrameParseError(f"IMU payload too short: {len(payload)} < {_IMU_LEN}")
    unpacked = struct.unpack(_IMU_FMT, payload[:_IMU_LEN])
    stamp, msg_id = unpacked[0], unpacked[1]
    quaternion = unpacked[2:6]
    angular_velocity = unpacked[6:9]
    linear_acceleration = unpacked[9:12]
    return ImuFrame(stamp, msg_id, quaternion, angular_velocity, linear_acceleration)


def _parse_scan(payload: bytes) -> ScanFrame:
    if len(payload) < _SCAN_PAYLOAD_LEN:
        raise FrameParseError(
            f"Scan payload too short: {len(payload)} < {_SCAN_PAYLOAD_LEN}"
        )
    stamp, msg_id, valid_points_num = struct.unpack(
        _SCAN_PREFIX_FMT, payload[:_SCAN_PREFIX_LEN]
    )
    valid_points_num = min(valid_points_num, POINTS_PER_SCAN)

    points = []
    offset = _SCAN_PREFIX_LEN
    for _ in range(valid_points_num):
        x, y, z, intensity, t, ring = struct.unpack(
            _POINT_FMT, payload[offset:offset + _POINT_LEN]
        )
        points.append((x, y, z, intensity, t, ring))
        offset += _POINT_LEN

    return ScanFrame(stamp, msg_id, points)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/gremlin/gremlin/lidar_viewer && python3 -m pytest tests/test_frame_parser.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/gremlin/gremlin
git add lidar_viewer/backend/frame_parser.py lidar_viewer/tests/test_frame_parser.py
git commit -m "feat(lidar_viewer): parse Scan/IMU UDP frames from the unitree bridge"
```

---

## Task 3: `accumulator.py` — windowed point buffer + range filter

**Files:**
- Create: `gremlin/lidar_viewer/backend/accumulator.py`
- Test: `gremlin/lidar_viewer/tests/test_accumulator.py`

**Interfaces:**
- Consumes: `ScanFrame` from `backend.frame_parser`
- Produces: `AccumulatedPoint(x: float, y: float, z: float, intensity: float, received_at: float)`
- Produces: `PointAccumulator(window_seconds: float = 3.0, max_range_m: float = 8.0)` with methods
  `add_scan(scan: ScanFrame, now: float | None = None) -> None` and
  `snapshot() -> list[AccumulatedPoint]`

- [ ] **Step 1: Write the failing tests**

```python
# gremlin/lidar_viewer/tests/test_accumulator.py
import pytest

from backend.accumulator import PointAccumulator
from backend.frame_parser import ScanFrame


def _scan(points_xyz, stamp=0.0, frame_id=1):
    # kazdy punkt jako (x, y, z, intensity, time, ring) - intensity/time/ring
    # nie sa istotne dla tych testow, ustawiamy stale wartosci
    points = [(x, y, z, 42.0, 0.0, 0) for (x, y, z) in points_xyz]
    return ScanFrame(stamp=stamp, id=frame_id, points=points)


def test_add_scan_keeps_points_within_range():
    acc = PointAccumulator(window_seconds=10.0, max_range_m=5.0)
    acc.add_scan(_scan([(1.0, 0.0, 0.0), (10.0, 0.0, 0.0)]), now=0.0)

    snapshot = acc.snapshot()

    assert len(snapshot) == 1
    assert snapshot[0].x == pytest.approx(1.0)


def test_add_scan_drops_points_beyond_max_range():
    acc = PointAccumulator(window_seconds=10.0, max_range_m=2.0)
    acc.add_scan(_scan([(3.0, 4.0, 0.0)]), now=0.0)  # distance = 5.0 > 2.0

    assert acc.snapshot() == []


def test_old_points_evicted_after_window_expires():
    acc = PointAccumulator(window_seconds=1.0, max_range_m=100.0)
    acc.add_scan(_scan([(1.0, 0.0, 0.0)]), now=0.0)
    acc.add_scan(_scan([(2.0, 0.0, 0.0)]), now=0.5)

    # w chwili t=1.6 pierwszy punkt (t=0.0) jest starszy niz okno 1.0s,
    # drugi (t=0.5) wciaz miesci sie w oknie [0.6, 1.6]
    acc.add_scan(_scan([]), now=1.6)  # pusty skan wymusza tylko eviction

    snapshot = acc.snapshot()
    xs = sorted(p.x for p in snapshot)
    assert xs == [2.0]


def test_intensity_is_preserved():
    acc = PointAccumulator(window_seconds=10.0, max_range_m=100.0)
    scan = ScanFrame(stamp=0.0, id=1, points=[(1.0, 0.0, 0.0, 77.0, 0.0, 0)])
    acc.add_scan(scan, now=0.0)

    assert acc.snapshot()[0].intensity == pytest.approx(77.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/gremlin/gremlin/lidar_viewer && python3 -m pytest tests/test_accumulator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.accumulator'`.

- [ ] **Step 3: Implement `accumulator.py`**

```python
# gremlin/lidar_viewer/backend/accumulator.py
"""
Bufor akumulacyjny chmury punktow: pojedynczy ScanFrame ma do 120 punktow
(jeden aux+dist packet z lidaru), pelny ksztalt 3D wymaga akumulacji wielu
skanow w oknie czasowym - inaczej chmura wyglada plasko/jak cienka wstazka
(potwierdzone empirycznie na analogicznym pipeline MAVLink).
"""

import math
import time
from collections import deque
from dataclasses import dataclass
from typing import List, Optional

from .frame_parser import ScanFrame


@dataclass
class AccumulatedPoint:
    x: float
    y: float
    z: float
    intensity: float
    received_at: float


class PointAccumulator:
    def __init__(self, window_seconds: float = 3.0, max_range_m: float = 8.0):
        self.window_seconds = window_seconds
        self.max_range_m = max_range_m
        self._points: "deque[AccumulatedPoint]" = deque()

    def add_scan(self, scan: ScanFrame, now: Optional[float] = None) -> None:
        now = now if now is not None else time.monotonic()
        for x, y, z, intensity, _t, _ring in scan.points:
            distance = math.sqrt(x * x + y * y + z * z)
            if distance > self.max_range_m:
                continue
            self._points.append(AccumulatedPoint(x, y, z, intensity, now))
        self._evict_old(now)

    def _evict_old(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._points and self._points[0].received_at < cutoff:
            self._points.popleft()

    def snapshot(self) -> List[AccumulatedPoint]:
        return list(self._points)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/gremlin/gremlin/lidar_viewer && python3 -m pytest tests/test_accumulator.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/gremlin/gremlin
git add lidar_viewer/backend/accumulator.py lidar_viewer/tests/test_accumulator.py
git commit -m "feat(lidar_viewer): windowed point accumulator with range filter"
```

---

## Task 4: `recorder.py` + `player.py` — record/replay raw UDP frames

**Files:**
- Create: `gremlin/lidar_viewer/backend/recorder.py`
- Create: `gremlin/lidar_viewer/backend/player.py`
- Test: `gremlin/lidar_viewer/tests/test_recorder_player.py`

**Interfaces:**
- Produces: `FrameRecorder(path: str)` with `write(raw_datagram: bytes, timestamp_ns: int | None = None) -> None` and `close() -> None`, usable as a context manager.
- Produces: `read_records(path: str) -> Iterator[tuple[int, bytes]]` (sync, yields `(timestamp_ns, raw_datagram)`)
- Produces: `FramePlayer(path: str)` with `async def aplay(self) -> AsyncIterator[bytes]` — sleeps between yields to reproduce original timing.

Recording file format (ours, not ROS): sequence of records, each
`struct.pack("<QI", timestamp_ns, len(datagram))` followed by the raw
datagram bytes (the same bytes `udp_listener` receives — header + payload,
unmodified).

- [ ] **Step 1: Write the failing tests**

```python
# gremlin/lidar_viewer/tests/test_recorder_player.py
import asyncio
import os
import struct
import tempfile

import pytest

from backend.player import FramePlayer, read_records
from backend.recorder import FrameRecorder


def test_recorder_writes_readable_records():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "rec.bin")
        with FrameRecorder(path) as rec:
            rec.write(b"\x01\x02\x03", timestamp_ns=1_000_000_000)
            rec.write(b"\x04\x05", timestamp_ns=1_000_500_000)

        records = list(read_records(path))

        assert records == [
            (1_000_000_000, b"\x01\x02\x03"),
            (1_000_500_000, b"\x04\x05"),
        ]


def test_read_records_raises_on_truncated_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "rec.bin")
        with open(path, "wb") as f:
            # naglowek deklaruje 10 bajtow payloadu, ale plik urywa sie po 2
            f.write(struct.pack("<QI", 0, 10))
            f.write(b"\x00\x00")

        with pytest.raises(EOFError):
            list(read_records(path))


def test_player_aplay_yields_datagrams_in_order():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "rec.bin")
        with FrameRecorder(path) as rec:
            rec.write(b"a", timestamp_ns=0)
            rec.write(b"b", timestamp_ns=1_000_000)  # 1ms later - keeps the test fast

        async def collect():
            player = FramePlayer(path)
            return [data async for data in player.aplay()]

        result = asyncio.run(collect())

        assert result == [b"a", b"b"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/gremlin/gremlin/lidar_viewer && python3 -m pytest tests/test_recorder_player.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `recorder.py`**

```python
# gremlin/lidar_viewer/backend/recorder.py
"""
Nagrywa surowe datagramy UDP (dokladnie te bajty, ktore odebral
udp_listener) do pliku, z timestampem monotonicznym per rekord. Format
wlasny (nie ROS/.bag): [uint64 timestamp_ns][uint32 length][dane].
"""

import struct
import time
from typing import Optional

_RECORD_HEADER_FMT = "<QI"
_RECORD_HEADER_LEN = struct.calcsize(_RECORD_HEADER_FMT)


class FrameRecorder:
    def __init__(self, path: str):
        self._file = open(path, "wb")

    def write(self, raw_datagram: bytes, timestamp_ns: Optional[int] = None) -> None:
        timestamp_ns = timestamp_ns if timestamp_ns is not None else time.monotonic_ns()
        header = struct.pack(_RECORD_HEADER_FMT, timestamp_ns, len(raw_datagram))
        self._file.write(header)
        self._file.write(raw_datagram)

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> "FrameRecorder":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
```

- [ ] **Step 4: Implement `player.py`**

```python
# gremlin/lidar_viewer/backend/player.py
"""
Odczytuje plik nagrania (format z recorder.py) i odtwarza surowe datagramy
z zachowaniem oryginalnych odstepow czasowych.
"""

import asyncio
import struct
from typing import AsyncIterator, Iterator, Tuple

_RECORD_HEADER_FMT = "<QI"
_RECORD_HEADER_LEN = struct.calcsize(_RECORD_HEADER_FMT)


def read_records(path: str) -> Iterator[Tuple[int, bytes]]:
    with open(path, "rb") as f:
        while True:
            header = f.read(_RECORD_HEADER_LEN)
            if len(header) == 0:
                return
            if len(header) < _RECORD_HEADER_LEN:
                raise EOFError("truncated recording file: incomplete record header")
            timestamp_ns, length = struct.unpack(_RECORD_HEADER_FMT, header)
            data = f.read(length)
            if len(data) < length:
                raise EOFError("truncated recording file: incomplete record payload")
            yield timestamp_ns, data


class FramePlayer:
    def __init__(self, path: str):
        self._path = path

    async def aplay(self) -> AsyncIterator[bytes]:
        prev_ts = None
        for timestamp_ns, data in read_records(self._path):
            if prev_ts is not None:
                delta_s = (timestamp_ns - prev_ts) / 1e9
                if delta_s > 0:
                    await asyncio.sleep(delta_s)
            prev_ts = timestamp_ns
            yield data
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /home/gremlin/gremlin/lidar_viewer && python3 -m pytest tests/test_recorder_player.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
cd /home/gremlin/gremlin
git add lidar_viewer/backend/recorder.py lidar_viewer/backend/player.py lidar_viewer/tests/test_recorder_player.py
git commit -m "feat(lidar_viewer): record and replay raw UDP frames"
```

---

## Task 5: `bridge_manager.py` — subprocess lifecycle for the bridge

**Files:**
- Create: `gremlin/lidar_viewer/backend/bridge_manager.py`
- Test: `gremlin/lidar_viewer/tests/test_bridge_manager.py`

**Interfaces:**
- Produces: `BridgeStartError(RuntimeError)`
- Produces: `BridgeManager(executable_path: str, serial_port: str, dest_ip: str = "127.0.0.1", dest_port: int = 12345)` with `start() -> None`, `is_alive() -> bool`, `stop() -> None`.

Tests use a real, tiny, cross-platform subprocess (`python3 -c "..."`) in
place of the real bridge binary, so they don't depend on `unilidar_sdk`
being built in this environment.

- [ ] **Step 1: Write the failing tests**

```python
# gremlin/lidar_viewer/tests/test_bridge_manager.py
import sys
import time

import pytest

from backend.bridge_manager import BridgeManager, BridgeStartError

_SLEEPY_SCRIPT = "import time; time.sleep(5)"
_INSTANT_EXIT_SCRIPT = "import sys; sys.exit(0)"


def test_start_and_is_alive():
    manager = BridgeManager(
        executable_path=sys.executable,
        serial_port="-c",  # argv passthrough trick, see step 3 note below
    )
    # przekazujemy dodatkowy argument skryptu przez podmiane argv w start()
    manager._extra_args = [_SLEEPY_SCRIPT]  # ustawiane tylko w tescie, patrz implementacja
    manager.start()
    try:
        assert manager.is_alive() is True
    finally:
        manager.stop()


def test_stop_terminates_process():
    manager = BridgeManager(executable_path=sys.executable, serial_port="-c")
    manager._extra_args = [_SLEEPY_SCRIPT]
    manager.start()
    manager.stop()

    assert manager.is_alive() is False


def test_is_alive_false_after_process_exits_on_its_own():
    manager = BridgeManager(executable_path=sys.executable, serial_port="-c")
    manager._extra_args = [_INSTANT_EXIT_SCRIPT]
    manager.start()
    time.sleep(0.3)

    assert manager.is_alive() is False


def test_start_raises_when_executable_missing():
    manager = BridgeManager(
        executable_path="/nie/istnieje/na/pewno/unilidar_publisher_udp",
        serial_port="/dev/ttyUSB0",
    )

    with pytest.raises(BridgeStartError):
        manager.start()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/gremlin/gremlin/lidar_viewer && python3 -m pytest tests/test_bridge_manager.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `bridge_manager.py`**

Note on the test hack above: real usage always calls
`[executable_path, serial_port, dest_ip, str(dest_port)]`. The tests need
to launch an arbitrary throwaway subprocess without a real bridge binary,
so `BridgeManager` supports an internal `_extra_args` override purely for
testability — documented in the docstring, not part of the public
contract real callers use.

```python
# gremlin/lidar_viewer/backend/bridge_manager.py
"""
Zarzadza cyklem zycia subprocessu unilidar_publisher_udp (bridge z SDK
Unitree, C++) - to on faktycznie otwiera port szeregowy lidaru i
retransmituje dane po UDP. Bridge sam wysyla komende NORMAL do lidaru po
starcie (zweryfikowane w zrodle unilidar_publisher_udp.cpp), wiec ten
modul nie musi tego robic.
"""

import subprocess
from typing import List, Optional


class BridgeStartError(RuntimeError):
    """Nie udalo sie uruchomic subprocessu bridge'a."""


class BridgeManager:
    def __init__(
        self,
        executable_path: str,
        serial_port: str,
        dest_ip: str = "127.0.0.1",
        dest_port: int = 12345,
    ):
        self.executable_path = executable_path
        self.serial_port = serial_port
        self.dest_ip = dest_ip
        self.dest_port = dest_port
        # Uzywane WYLACZNIE w testach, zeby podmienic argumenty na
        # nieszkodliwy skrypt zamiast prawdziwej binarki bridge'a.
        self._extra_args: Optional[List[str]] = None
        self._process: Optional[subprocess.Popen] = None

    def start(self) -> None:
        if self._process is not None:
            return

        args = [self.executable_path]
        if self._extra_args is not None:
            args += self._extra_args
        else:
            args += [self.serial_port, self.dest_ip, str(self.dest_port)]

        try:
            self._process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        except FileNotFoundError as exc:
            raise BridgeStartError(
                f"Nie znaleziono binarki bridge'a: {self.executable_path}"
            ) from exc

    def is_alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def stop(self) -> None:
        if self._process is None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()
        self._process = None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/gremlin/gremlin/lidar_viewer && python3 -m pytest tests/test_bridge_manager.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/gremlin/gremlin
git add lidar_viewer/backend/bridge_manager.py lidar_viewer/tests/test_bridge_manager.py
git commit -m "feat(lidar_viewer): manage the unilidar_publisher_udp bridge subprocess"
```

---

## Task 6: `udp_listener.py` — asyncio UDP receiver

**Files:**
- Create: `gremlin/lidar_viewer/backend/udp_listener.py`
- Test: `gremlin/lidar_viewer/tests/test_udp_listener.py`

**Interfaces:**
- Produces: `async def create_udp_listener(host: str, port: int, on_datagram: Callable[[bytes], None]) -> asyncio.DatagramTransport`

Tested with real loopback UDP traffic (bind port 0 to get an OS-assigned
free port, send from a plain `socket`).

- [ ] **Step 1: Write the failing test**

```python
# gremlin/lidar_viewer/tests/test_udp_listener.py
import asyncio
import socket

import pytest

from backend.udp_listener import create_udp_listener


@pytest.mark.asyncio
async def test_received_datagrams_are_forwarded():
    received = []

    transport = await create_udp_listener("127.0.0.1", 0, received.append)
    try:
        host, port = transport.get_extra_info("sockname")

        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender.sendto(b"hello", (host, port))
        sender.close()

        for _ in range(50):  # do ~0.5s na dotarcie datagramu
            if received:
                break
            await asyncio.sleep(0.01)

        assert received == [b"hello"]
    finally:
        transport.close()
```

- [ ] **Step 2: Add `pytest-asyncio` to requirements and configure it**

```
# append to gremlin/lidar_viewer/requirements.txt
pytest-asyncio>=0.24
```

```bash
/home/gremlin/gremlin/.venv/bin/pip install pytest-asyncio
```

Create `gremlin/lidar_viewer/pytest.ini`:

```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd /home/gremlin/gremlin/lidar_viewer && /home/gremlin/gremlin/.venv/bin/python3 -m pytest tests/test_udp_listener.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Implement `udp_listener.py`**

```python
# gremlin/lidar_viewer/backend/udp_listener.py
"""Prosty nasluch UDP oparty o asyncio.DatagramProtocol."""

import asyncio
from typing import Callable


class _UdpListenerProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_datagram: Callable[[bytes], None]):
        self._on_datagram = on_datagram

    def datagram_received(self, data: bytes, addr) -> None:
        self._on_datagram(data)


async def create_udp_listener(
    host: str, port: int, on_datagram: Callable[[bytes], None]
) -> asyncio.DatagramTransport:
    loop = asyncio.get_running_loop()
    transport, _protocol = await loop.create_datagram_endpoint(
        lambda: _UdpListenerProtocol(on_datagram),
        local_addr=(host, port),
    )
    return transport
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd /home/gremlin/gremlin/lidar_viewer && /home/gremlin/gremlin/.venv/bin/python3 -m pytest tests/test_udp_listener.py -v`
Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
cd /home/gremlin/gremlin
git add lidar_viewer/backend/udp_listener.py lidar_viewer/tests/test_udp_listener.py lidar_viewer/requirements.txt lidar_viewer/pytest.ini
git commit -m "feat(lidar_viewer): asyncio UDP listener"
```

---

## Task 7: `ws_server.py` — binary/JSON frame encoding + client broadcast

**Files:**
- Create: `gremlin/lidar_viewer/backend/ws_server.py`
- Test: `gremlin/lidar_viewer/tests/test_ws_server.py`

**Interfaces:**
- Produces: constants `SCAN_WS_TYPE = 1`, `IMU_WS_TYPE = 2`
- Produces: `encode_scan_frame(points: list[tuple[float,float,float,float]]) -> bytes`
- Produces: `encode_imu_frame(quaternion, angular_velocity, linear_acceleration) -> bytes`
- Produces: `encode_metrics_frame(fps: float, points_in_window: int, latency_ms: float) -> str`
- Produces: `ClientRegistry` with `add(ws)`, `remove(ws)`, `async broadcast(message: bytes | str) -> None`

**Wire format (binary, little-endian, all float data 4-byte-aligned from
message start):**
- Scan: `uint32 type(=1)` + `uint32 pointCount` + `pointCount × float32×4 (x,y,z,intensity)` — float data starts at byte 8.
- IMU: `uint32 type(=2)` + `float32×4 quaternion` + `float32×3 angular_velocity` + `float32×3 linear_acceleration` — float data starts at byte 4.
- Metrics: JSON text frame `{"type": "metrics", "fps": <float>, "points_in_window": <int>, "latency_ms": <float>}`.

- [ ] **Step 1: Write the failing tests**

```python
# gremlin/lidar_viewer/tests/test_ws_server.py
import json
import struct

import pytest

from backend.ws_server import (
    ClientRegistry,
    IMU_WS_TYPE,
    SCAN_WS_TYPE,
    encode_imu_frame,
    encode_metrics_frame,
    encode_scan_frame,
)


def test_encode_scan_frame_layout():
    points = [(1.0, 2.0, 3.0, 42.0), (4.0, 5.0, 6.0, 43.0)]
    encoded = encode_scan_frame(points)

    msg_type, point_count = struct.unpack_from("<II", encoded, 0)
    assert msg_type == SCAN_WS_TYPE
    assert point_count == 2
    assert len(encoded) == 8 + 2 * 4 * 4

    floats = struct.unpack_from("<8f", encoded, 8)
    assert floats == pytest.approx((1.0, 2.0, 3.0, 42.0, 4.0, 5.0, 6.0, 43.0))


def test_encode_scan_frame_empty():
    encoded = encode_scan_frame([])
    msg_type, point_count = struct.unpack_from("<II", encoded, 0)
    assert msg_type == SCAN_WS_TYPE
    assert point_count == 0
    assert len(encoded) == 8


def test_encode_imu_frame_layout():
    quaternion = (0.0, 0.0, 0.0, 1.0)
    angular_velocity = (0.1, 0.2, 0.3)
    linear_acceleration = (0.0, 0.0, 9.81)
    encoded = encode_imu_frame(quaternion, angular_velocity, linear_acceleration)

    msg_type = struct.unpack_from("<I", encoded, 0)[0]
    assert msg_type == IMU_WS_TYPE
    assert len(encoded) == 4 + 10 * 4

    floats = struct.unpack_from("<10f", encoded, 4)
    assert floats == pytest.approx(quaternion + angular_velocity + linear_acceleration)


def test_encode_metrics_frame_is_valid_json():
    text = encode_metrics_frame(fps=12.5, points_in_window=4821, latency_ms=17.3)
    parsed = json.loads(text)

    assert parsed == {
        "type": "metrics",
        "fps": 12.5,
        "points_in_window": 4821,
        "latency_ms": 17.3,
    }


@pytest.mark.asyncio
async def test_client_registry_broadcast_reaches_all_clients():
    sent = {"a": [], "b": []}

    class FakeWs:
        def __init__(self, key):
            self.key = key

        async def send(self, message):
            sent[self.key].append(message)

    registry = ClientRegistry()
    registry.add(FakeWs("a"))
    registry.add(FakeWs("b"))

    await registry.broadcast(b"hello")

    assert sent == {"a": [b"hello"], "b": [b"hello"]}


@pytest.mark.asyncio
async def test_client_registry_drops_clients_that_error_on_send():
    import websockets

    class FailingWs:
        async def send(self, message):
            raise websockets.ConnectionClosed(None, None)

    registry = ClientRegistry()
    failing = FailingWs()
    registry.add(failing)

    await registry.broadcast(b"hello")  # nie powinno rzucic wyjatku

    assert failing not in registry._clients
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/gremlin/gremlin/lidar_viewer && /home/gremlin/gremlin/.venv/bin/python3 -m pytest tests/test_ws_server.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `ws_server.py`**

```python
# gremlin/lidar_viewer/backend/ws_server.py
"""
Kodowanie ramek binarnych/JSON wysylanych do przegladarki przez WS oraz
rejestr podlaczonych klientow z broadcastem.

WAZNE: wszystkie naglowki maja rozmiar bedacy wielokrotnoscia 4 bajtow, bo
JS Float32Array rzuca RangeError, jesli byteOffset nie jest wielokrotnoscia
4 - stad uint32 (nie uint8) na pole "type".
"""

import json
import struct
from typing import Iterable, Tuple, Union

import websockets

SCAN_WS_TYPE = 1
IMU_WS_TYPE = 2

_SCAN_HEADER_FMT = "<II"  # type, pointCount
_IMU_FMT = "<I10f"  # type + quat(4) + angvel(3) + linacc(3)


def encode_scan_frame(points: Iterable[Tuple[float, float, float, float]]) -> bytes:
    points = list(points)
    header = struct.pack(_SCAN_HEADER_FMT, SCAN_WS_TYPE, len(points))
    if not points:
        return header
    flat = [v for point in points for v in point]
    body = struct.pack(f"<{len(flat)}f", *flat)
    return header + body


def encode_imu_frame(
    quaternion: Tuple[float, float, float, float],
    angular_velocity: Tuple[float, float, float],
    linear_acceleration: Tuple[float, float, float],
) -> bytes:
    return struct.pack(
        _IMU_FMT,
        IMU_WS_TYPE,
        *quaternion,
        *angular_velocity,
        *linear_acceleration,
    )


def encode_metrics_frame(fps: float, points_in_window: int, latency_ms: float) -> str:
    return json.dumps(
        {
            "type": "metrics",
            "fps": fps,
            "points_in_window": points_in_window,
            "latency_ms": latency_ms,
        }
    )


class ClientRegistry:
    def __init__(self):
        self._clients = set()

    def add(self, ws) -> None:
        self._clients.add(ws)

    def remove(self, ws) -> None:
        self._clients.discard(ws)

    async def broadcast(self, message: Union[bytes, str]) -> None:
        stale = []
        for ws in list(self._clients):
            try:
                await ws.send(message)
            except websockets.ConnectionClosed:
                stale.append(ws)
        for ws in stale:
            self._clients.discard(ws)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/gremlin/gremlin/lidar_viewer && /home/gremlin/gremlin/.venv/bin/python3 -m pytest tests/test_ws_server.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/gremlin/gremlin
git add lidar_viewer/backend/ws_server.py lidar_viewer/tests/test_ws_server.py
git commit -m "feat(lidar_viewer): WS binary/JSON frame encoding and client broadcast"
```

---

## Task 8: `app.py` — CLI entrypoint wiring everything together

**Files:**
- Create: `gremlin/lidar_viewer/backend/app.py`
- Test: `gremlin/lidar_viewer/tests/test_app_replay_smoke.py`

**Interfaces:**
- Consumes: everything produced in Tasks 2–7.
- Produces: `parse_args(argv: list[str] | None = None) -> argparse.Namespace`, `class App` (constructor takes parsed args), `def main() -> None` (real CLI entrypoint, calls `asyncio.run`).

This is an integration task: the only new *logic* is the CLI argument
parsing, the `App` class's datagram handling, and the two periodic loops
(broadcast, metrics). It's tested end-to-end via `--replay` against a tiny
synthetic recording — no real hardware or bridge binary needed.

- [ ] **Step 1: Write the failing smoke test**

```python
# gremlin/lidar_viewer/tests/test_app_replay_smoke.py
import struct

import pytest

from backend.app import App, parse_args
from backend.recorder import FrameRecorder

_HEADER_FMT = "<II"
_IMU_FMT = "<dI4f3f3f"
_POINT_FMT = "<fffffI"
_SCAN_PREFIX_FMT = "<dII"
_POINTS_PER_SCAN = 120


def _scan_datagram(x, y, z, intensity):
    points = [(x, y, z, intensity, 0.0, 0)] + [(0.0, 0.0, 0.0, 0.0, 0.0, 0)] * (
        _POINTS_PER_SCAN - 1
    )
    points_bytes = b"".join(struct.pack(_POINT_FMT, *p) for p in points)
    payload = struct.pack(_SCAN_PREFIX_FMT, 1.0, 1, 1) + points_bytes
    header = struct.pack(_HEADER_FMT, 102, len(payload))
    return header + payload


def _imu_datagram():
    payload = struct.pack(
        _IMU_FMT, 1.0, 1, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 9.81
    )
    header = struct.pack(_HEADER_FMT, 101, len(payload))
    return header + payload


def test_parse_args_requires_serial_port_or_replay():
    with pytest.raises(SystemExit):
        parse_args([])


def test_parse_args_accepts_replay_alone():
    args = parse_args(["--replay", "somefile.bin"])
    assert args.replay == "somefile.bin"
    assert args.serial_port is None


def test_app_handle_datagram_feeds_accumulator_and_latest_imu(tmp_path):
    args = parse_args(["--replay", "unused.bin"])
    app = App(args)

    app.handle_datagram(_scan_datagram(1.0, 2.0, 3.0, 99.0))
    app.handle_datagram(_imu_datagram())

    snapshot = app.accumulator.snapshot()
    assert len(snapshot) == 1
    assert snapshot[0].x == pytest.approx(1.0)
    assert app.latest_imu is not None
    assert app.latest_imu.quaternion == pytest.approx((0.0, 0.0, 0.0, 1.0))


def test_app_records_when_configured(tmp_path):
    record_path = tmp_path / "session.bin"
    args = parse_args(["--replay", "unused.bin", "--record", str(record_path)])
    app = App(args)

    datagram = _scan_datagram(1.0, 2.0, 3.0, 99.0)
    app.handle_datagram(datagram)
    app.recorder.close()

    from backend.player import read_records

    records = list(read_records(str(record_path)))
    assert len(records) == 1
    assert records[0][1] == datagram
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/gremlin/gremlin/lidar_viewer && /home/gremlin/gremlin/.venv/bin/python3 -m pytest tests/test_app_replay_smoke.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `app.py`**

```python
# gremlin/lidar_viewer/backend/app.py
"""
CLI entrypoint: spina bridge_manager, udp_listener, frame_parser,
accumulator, recorder/player i ws_server w jedna dzialajaca aplikacje.

Tryb live:    python3 -m backend.app --serial-port /dev/ttyUSB0 --bridge-path <sciezka>
Tryb replay:  python3 -m backend.app --replay nagranie.bin
"""

import argparse
import asyncio
import logging
import time
from typing import Optional

import websockets

from .accumulator import PointAccumulator
from .bridge_manager import BridgeManager
from .frame_parser import FrameParseError, ImuFrame, ScanFrame, parse_udp_datagram
from .player import FramePlayer
from .recorder import FrameRecorder
from .udp_listener import create_udp_listener
from .ws_server import ClientRegistry, encode_imu_frame, encode_metrics_frame, encode_scan_frame

logger = logging.getLogger("lidar_viewer")

BROADCAST_INTERVAL_S = 0.05  # ~20Hz gorny limit czestotliwosci wysylki chmury
METRICS_INTERVAL_S = 1.0
BRIDGE_MAX_RESTARTS = 3


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Standalone Unitree L1 UDP viewer")
    parser.add_argument("--serial-port", default=None, help="Port szeregowy lidaru (tryb live)")
    parser.add_argument("--replay", default=None, help="Plik nagrania do odtworzenia zamiast trybu live")
    parser.add_argument("--record", default=None, help="Sciezka pliku do nagrania surowych ramek live")
    parser.add_argument("--udp-host", default="127.0.0.1")
    parser.add_argument("--udp-port", type=int, default=12345)
    parser.add_argument("--ws-host", default="0.0.0.0")
    parser.add_argument("--ws-port", type=int, default=8080)
    parser.add_argument(
        "--bridge-path",
        default="unilidar_publisher_udp",
        help="Sciezka do binarki bridge'a (unilidar_publisher_udp)",
    )
    parser.add_argument("--window-seconds", type=float, default=3.0)
    parser.add_argument("--max-range-m", type=float, default=8.0)
    args = parser.parse_args(argv)

    if not args.replay and not args.serial_port:
        parser.error("wymagany --serial-port (tryb live) albo --replay <plik>")
    return args


class App:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.accumulator = PointAccumulator(
            window_seconds=args.window_seconds, max_range_m=args.max_range_m
        )
        self.clients = ClientRegistry()
        self.recorder: Optional[FrameRecorder] = FrameRecorder(args.record) if args.record else None
        self.latest_imu: Optional[ImuFrame] = None
        self._scan_count = 0
        self._scan_count_window_start = time.monotonic()

    def handle_datagram(self, data: bytes) -> None:
        if self.recorder is not None:
            self.recorder.write(data)
        try:
            frame = parse_udp_datagram(data)
        except FrameParseError as exc:
            logger.debug("odrzucono uszkodzona ramke: %s", exc)
            return

        if isinstance(frame, ScanFrame):
            self.accumulator.add_scan(frame)
            self._scan_count += 1
        elif isinstance(frame, ImuFrame):
            self.latest_imu = frame

    async def broadcast_loop(self) -> None:
        while True:
            await asyncio.sleep(BROADCAST_INTERVAL_S)
            points = [(p.x, p.y, p.z, p.intensity) for p in self.accumulator.snapshot()]
            if points:
                await self.clients.broadcast(encode_scan_frame(points))
            if self.latest_imu is not None:
                await self.clients.broadcast(
                    encode_imu_frame(
                        self.latest_imu.quaternion,
                        self.latest_imu.angular_velocity,
                        self.latest_imu.linear_acceleration,
                    )
                )

    async def metrics_loop(self) -> None:
        while True:
            await asyncio.sleep(METRICS_INTERVAL_S)
            now = time.monotonic()
            elapsed = now - self._scan_count_window_start
            fps = self._scan_count / elapsed if elapsed > 0 else 0.0
            self._scan_count = 0
            self._scan_count_window_start = now

            latency_ms = 0.0
            if self.latest_imu is not None:
                # best-effort: zaklada zsynchronizowane zegary hosta i
                # lidaru; jesli nie sa, ta wartosc jest tylko orientacyjna
                latency_ms = max(0.0, (time.time() - self.latest_imu.stamp) * 1000.0)

            await self.clients.broadcast(
                encode_metrics_frame(
                    fps=fps,
                    points_in_window=len(self.accumulator.snapshot()),
                    latency_ms=latency_ms,
                )
            )

    async def replay_loop(self, path: str) -> None:
        player = FramePlayer(path)
        async for data in player.aplay():
            self.handle_datagram(data)

    async def ws_handler(self, websocket) -> None:
        self.clients.add(websocket)
        try:
            await websocket.wait_closed()
        finally:
            self.clients.remove(websocket)


async def _run_live(app: App, args: argparse.Namespace) -> None:
    bridge = BridgeManager(
        executable_path=args.bridge_path,
        serial_port=args.serial_port,
        dest_ip=args.udp_host,
        dest_port=args.udp_port,
    )
    bridge.start()

    transport = await create_udp_listener(args.udp_host, args.udp_port, app.handle_datagram)

    restarts = 0
    try:
        while True:
            await asyncio.sleep(1.0)
            if not bridge.is_alive():
                restarts += 1
                if restarts > BRIDGE_MAX_RESTARTS:
                    logger.error("Bridge padl %d razy - poddaje sie.", restarts)
                    raise SystemExit(1)
                logger.warning("Bridge nie zyje, restart (%d/%d)...", restarts, BRIDGE_MAX_RESTARTS)
                bridge.start()
    finally:
        transport.close()
        bridge.stop()


async def main_async() -> None:
    logging.basicConfig(level=logging.INFO)
    args = parse_args()
    app = App(args)

    ws_server = await websockets.serve(app.ws_handler, args.ws_host, args.ws_port)
    background_tasks = [
        asyncio.create_task(app.broadcast_loop()),
        asyncio.create_task(app.metrics_loop()),
    ]

    try:
        if args.replay:
            await app.replay_loop(args.replay)
        else:
            await _run_live(app, args)
    finally:
        for task in background_tasks:
            task.cancel()
        ws_server.close()
        await ws_server.wait_closed()
        if app.recorder is not None:
            app.recorder.close()


def main() -> None:
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/gremlin/gremlin/lidar_viewer && /home/gremlin/gremlin/.venv/bin/python3 -m pytest tests/test_app_replay_smoke.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run the full backend test suite to confirm nothing regressed**

Run: `cd /home/gremlin/gremlin/lidar_viewer && /home/gremlin/gremlin/.venv/bin/python3 -m pytest tests/ -v --ignore=tests/test_convert_bag.py`
Expected: all passed (Tasks 2–8's tests combined; `test_convert_bag.py` doesn't exist yet, hence the ignore — remove that flag once Task 12 lands).

- [ ] **Step 6: Commit**

```bash
cd /home/gremlin/gremlin
git add lidar_viewer/backend/app.py lidar_viewer/tests/test_app_replay_smoke.py
git commit -m "feat(lidar_viewer): CLI entrypoint wiring bridge/UDP/WS/replay together"
```

---

## Task 9: Vendor Three.js locally

**Files:**
- Create: `gremlin/lidar_viewer/frontend/js/vendor/three.min.js`

**Interfaces:** none (static asset) — later frontend tasks load this via
`<script src="js/vendor/three.min.js"></script>` and use the global
`THREE` object it defines (r128 is the UMD/global build, not an ES
module — matches the earlier working prototype, avoids needing an
import-map or bundler).

- [ ] **Step 1: Download the pinned version**

```bash
mkdir -p /home/gremlin/gremlin/lidar_viewer/frontend/js/vendor
curl -sL https://raw.githubusercontent.com/mrdoob/three.js/r128/build/three.min.js \
  -o /home/gremlin/gremlin/lidar_viewer/frontend/js/vendor/three.min.js
```

- [ ] **Step 2: Verify it downloaded correctly (not an HTML error page)**

```bash
head -c 200 /home/gremlin/gremlin/lidar_viewer/frontend/js/vendor/three.min.js
wc -c /home/gremlin/gremlin/lidar_viewer/frontend/js/vendor/three.min.js
```

Expected: output starts with JS (e.g. `/**\n * @license...` or minified
code), not `<!DOCTYPE html>`; file size in the hundreds of KB (r128's
`three.min.js` is roughly 600KB).

- [ ] **Step 3: Commit the vendored file**

```bash
cd /home/gremlin/gremlin
git add lidar_viewer/frontend/js/vendor/three.min.js
git commit -m "chore(lidar_viewer): vendor three.js r128 locally, no CDN at runtime"
```

---

## Task 10: Frontend pure-logic modules — `color.js` and `ws_client.js`

**Files:**
- Create: `gremlin/lidar_viewer/frontend/js/color.js`
- Create: `gremlin/lidar_viewer/frontend/js/ws_client.js`
- Test: `gremlin/lidar_viewer/tests/js/test_color.js`
- Test: `gremlin/lidar_viewer/tests/js/test_ws_client.js`

**Interfaces:**
- Produces (`color.js`): `intensityToColor(intensity: number, minIntensity: number, maxIntensity: number) -> [r: number, g: number, b: number]` (0-1 range each), exported via `module.exports` (Node-testable) and also assigned to `window.intensityToColor` when no `module` exists (browser).
- Produces (`ws_client.js`): `SCAN_WS_TYPE = 1`, `IMU_WS_TYPE = 2`, `decodeMessage(data: ArrayBuffer | string) -> {type: 'scan', points: Float32Array, pointCount: number} | {type: 'imu', quaternion: Float32Array, angularVelocity: Float32Array, linearAcceleration: Float32Array} | {type: 'metrics', fps: number, pointsInWindow: number, latencyMs: number}`. Same dual export pattern as `color.js`.

These two files contain zero DOM/WebSocket-object access, so they run
under plain `node` without a browser — that's what makes them testable in
this environment.

- [ ] **Step 1: Write the failing tests**

```javascript
// gremlin/lidar_viewer/tests/js/test_color.js
const assert = require('assert');
const { intensityToColor } = require('../../frontend/js/color.js');

// niska intensywnosc -> blizej pierwszego koloru gradientu
{
  const [r, g, b] = intensityToColor(0, 0, 100);
  assert.ok(r >= 0 && r <= 1 && g >= 0 && g <= 1 && b >= 0 && b <= 1, 'zakres 0-1');
}

// wartosc dokladnie w polowie zakresu daje wynik miedzy skrajnymi kolorami
{
  const low = intensityToColor(0, 0, 100);
  const mid = intensityToColor(50, 0, 100);
  const high = intensityToColor(100, 0, 100);
  assert.notDeepStrictEqual(low, high, 'skrajne wartosci daja rozne kolory');
  assert.notDeepStrictEqual(mid, low);
  assert.notDeepStrictEqual(mid, high);
}

// zdegenerowany zakres (min == max) nie rzuca wyjatku i zwraca poprawny kolor
{
  const [r, g, b] = intensityToColor(42, 10, 10);
  assert.ok(Number.isFinite(r) && Number.isFinite(g) && Number.isFinite(b));
}

// wartosci spoza zakresu sa przycinane (clamped), nie ekstrapolowane
{
  const belowRange = intensityToColor(-50, 0, 100);
  const atMin = intensityToColor(0, 0, 100);
  assert.deepStrictEqual(belowRange, atMin);

  const aboveRange = intensityToColor(500, 0, 100);
  const atMax = intensityToColor(100, 0, 100);
  assert.deepStrictEqual(aboveRange, atMax);
}

console.log('test_color.js: wszystkie testy przeszly');
```

```javascript
// gremlin/lidar_viewer/tests/js/test_ws_client.js
const assert = require('assert');
const { decodeMessage, SCAN_WS_TYPE, IMU_WS_TYPE } = require('../../frontend/js/ws_client.js');

function buildScanBuffer(points) {
  const buf = new ArrayBuffer(8 + points.length * 16);
  const view = new DataView(buf);
  view.setUint32(0, SCAN_WS_TYPE, true);
  view.setUint32(4, points.length, true);
  let offset = 8;
  for (const [x, y, z, intensity] of points) {
    view.setFloat32(offset, x, true); offset += 4;
    view.setFloat32(offset, y, true); offset += 4;
    view.setFloat32(offset, z, true); offset += 4;
    view.setFloat32(offset, intensity, true); offset += 4;
  }
  return buf;
}

function buildImuBuffer(quaternion, angularVelocity, linearAcceleration) {
  const buf = new ArrayBuffer(4 + 40);
  const view = new DataView(buf);
  view.setUint32(0, IMU_WS_TYPE, true);
  const floats = [...quaternion, ...angularVelocity, ...linearAcceleration];
  let offset = 4;
  for (const f of floats) {
    view.setFloat32(offset, f, true);
    offset += 4;
  }
  return buf;
}

// dekodowanie ramki Scan
{
  const buf = buildScanBuffer([[1, 2, 3, 42], [4, 5, 6, 43]]);
  const result = decodeMessage(buf);
  assert.strictEqual(result.type, 'scan');
  assert.strictEqual(result.pointCount, 2);
  assert.deepStrictEqual(Array.from(result.points), [1, 2, 3, 42, 4, 5, 6, 43]);
}

// dekodowanie pustej ramki Scan (0 punktow) nie rzuca wyjatku
{
  const buf = buildScanBuffer([]);
  const result = decodeMessage(buf);
  assert.strictEqual(result.type, 'scan');
  assert.strictEqual(result.pointCount, 0);
  assert.strictEqual(result.points.length, 0);
}

// dekodowanie ramki IMU
{
  const buf = buildImuBuffer([0, 0, 0, 1], [0.1, 0.2, 0.3], [0, 0, 9.81]);
  const result = decodeMessage(buf);
  assert.strictEqual(result.type, 'imu');
  assert.deepStrictEqual(Array.from(result.quaternion), [0, 0, 0, 1]);
  assert.ok(Math.abs(result.angularVelocity[0] - 0.1) < 1e-6);
  assert.ok(Math.abs(result.linearAcceleration[2] - 9.81) < 1e-4);
}

// dekodowanie ramki metryk (tekst JSON)
{
  const text = JSON.stringify({ type: 'metrics', fps: 12.5, points_in_window: 4821, latency_ms: 17.3 });
  const result = decodeMessage(text);
  assert.strictEqual(result.type, 'metrics');
  assert.strictEqual(result.fps, 12.5);
  assert.strictEqual(result.pointsInWindow, 4821);
  assert.strictEqual(result.latencyMs, 17.3);
}

console.log('test_ws_client.js: wszystkie testy przeszly');
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
cd /home/gremlin/gremlin/lidar_viewer
node tests/js/test_color.js
node tests/js/test_ws_client.js
```
Expected: `Error: Cannot find module '../../frontend/js/color.js'` (and same for `ws_client.js`).

- [ ] **Step 3: Implement `color.js`**

```javascript
// gremlin/lidar_viewer/frontend/js/color.js
/**
 * Mapuje intensywnosc odbicia na kolor RGB (0-1 kazdy kanal), z
 * automatyczna normalizacja min/max przekazywana przez wywolujacego (okno
 * danych zmienia sie w czasie, wiec normalizacja nie jest stala).
 * Gradient: niebieski (slabe odbicie) -> zolty -> czerwony (silne odbicie).
 */
function intensityToColor(intensity, minIntensity, maxIntensity) {
  const range = maxIntensity - minIntensity;
  let t = range > 0 ? (intensity - minIntensity) / range : 0.5;
  t = Math.max(0, Math.min(1, t)); // clamp, nie ekstrapoluj

  const stops = [
    [0.1, 0.3, 0.9], // niebieski
    [0.95, 0.8, 0.2], // zolty
    [0.9, 0.15, 0.15], // czerwony
  ];
  const scaled = t * (stops.length - 1);
  const i = Math.min(Math.floor(scaled), stops.length - 2);
  const localT = scaled - i;
  const a = stops[i];
  const b = stops[i + 1];
  return [
    a[0] + (b[0] - a[0]) * localT,
    a[1] + (b[1] - a[1]) * localT,
    a[2] + (b[2] - a[2]) * localT,
  ];
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { intensityToColor };
} else {
  window.intensityToColor = intensityToColor;
}
```

- [ ] **Step 4: Implement `ws_client.js`**

```javascript
// gremlin/lidar_viewer/frontend/js/ws_client.js
/**
 * Dekoduje wiadomosci WS z backendu lidar_viewer. Format wg
 * backend/ws_server.py: Scan/IMU binarnie (naglowek uint32 zawsze
 * wyrownany do 4 bajtow, zeby Float32Array nie rzucal RangeError),
 * metryki jako tekst JSON.
 */

const SCAN_WS_TYPE = 1;
const IMU_WS_TYPE = 2;

function decodeMessage(data) {
  if (typeof data === 'string') {
    const parsed = JSON.parse(data);
    return {
      type: 'metrics',
      fps: parsed.fps,
      pointsInWindow: parsed.points_in_window,
      latencyMs: parsed.latency_ms,
    };
  }

  const view = new DataView(data);
  const msgType = view.getUint32(0, true);

  if (msgType === SCAN_WS_TYPE) {
    const pointCount = view.getUint32(4, true);
    const points = new Float32Array(data, 8, pointCount * 4);
    return { type: 'scan', points, pointCount };
  }

  if (msgType === IMU_WS_TYPE) {
    const floats = new Float32Array(data, 4, 10);
    return {
      type: 'imu',
      quaternion: floats.subarray(0, 4),
      angularVelocity: floats.subarray(4, 7),
      linearAcceleration: floats.subarray(7, 10),
    };
  }

  throw new Error(`nieznany typ wiadomosci WS: ${msgType}`);
}

function connect(url, { onScan, onImu, onMetrics }) {
  const ws = new WebSocket(url);
  ws.binaryType = 'arraybuffer';

  ws.addEventListener('message', (event) => {
    const decoded = decodeMessage(event.data);
    if (decoded.type === 'scan') onScan(decoded);
    else if (decoded.type === 'imu') onImu(decoded);
    else if (decoded.type === 'metrics') onMetrics(decoded);
  });

  return ws;
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { decodeMessage, connect, SCAN_WS_TYPE, IMU_WS_TYPE };
} else {
  window.wsClient = { decodeMessage, connect, SCAN_WS_TYPE, IMU_WS_TYPE };
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run:
```bash
cd /home/gremlin/gremlin/lidar_viewer
node tests/js/test_color.js
node tests/js/test_ws_client.js
```
Expected: both print their "wszystkie testy przeszly" line, no assertion errors.

- [ ] **Step 6: Commit**

```bash
cd /home/gremlin/gremlin
git add lidar_viewer/frontend/js/color.js lidar_viewer/frontend/js/ws_client.js lidar_viewer/tests/js/
git commit -m "feat(lidar_viewer): frontend intensity coloring and WS binary decoding"
```

---

## Task 11: Frontend rendering — `viewer.js`, `pointcloud.js`, panels, `index.html`

**Files:**
- Create: `gremlin/lidar_viewer/frontend/js/viewer.js`
- Create: `gremlin/lidar_viewer/frontend/js/pointcloud.js`
- Create: `gremlin/lidar_viewer/frontend/js/imu_panel.js`
- Create: `gremlin/lidar_viewer/frontend/js/metrics_panel.js`
- Create: `gremlin/lidar_viewer/frontend/js/main.js`
- Create: `gremlin/lidar_viewer/frontend/index.html`
- Create: `gremlin/lidar_viewer/frontend/css/style.css`

**Interfaces:**
- Consumes: global `THREE` (from vendored script), `wsClient.connect`/`decodeMessage` (Task 10), `intensityToColor` (Task 10).
- Produces: `createViewer(canvas: HTMLCanvasElement) -> {scene, camera, renderer, render: () => void, setPoints: (points: Float32Array, pointCount: number) => void}` in `viewer.js` + `pointcloud.js` combined (kept as two files per the file-structure responsibility split, but `viewer.js` owns the public `createViewer` used by `main.js`).

This task touches the DOM/WebGL and cannot be exercised by an automated
test in this environment (no browser here). It gets a documented manual
verification procedure instead — this is stated explicitly, not silently
skipped.

- [ ] **Step 1: Implement `pointcloud.js`** (BufferGeometry wrapper, in-place updates)

```javascript
// gremlin/lidar_viewer/frontend/js/pointcloud.js
/**
 * Owija THREE.Points z preallokowanymi buforami, zeby aktualizacja co
 * ramke Scan nie przebudowywala calej geometrii (kosztowne przy live
 * streamie) - tylko .set() na istniejacej Float32Array + needsUpdate.
 */
function createPointCloud(THREE, maxPoints) {
  const positions = new Float32Array(maxPoints * 3);
  const colors = new Float32Array(maxPoints * 3);

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  geometry.setDrawRange(0, 0);

  const material = new THREE.PointsMaterial({ size: 0.03, vertexColors: true });
  const points = new THREE.Points(geometry, material);

  function update(flatXyzIntensity, pointCount, intensityToColor) {
    const count = Math.min(pointCount, maxPoints);

    let minIntensity = Infinity;
    let maxIntensity = -Infinity;
    for (let i = 0; i < count; i++) {
      const intensity = flatXyzIntensity[i * 4 + 3];
      if (intensity < minIntensity) minIntensity = intensity;
      if (intensity > maxIntensity) maxIntensity = intensity;
    }
    if (!Number.isFinite(minIntensity)) { minIntensity = 0; maxIntensity = 1; }

    const posAttr = geometry.getAttribute('position');
    const colorAttr = geometry.getAttribute('color');

    for (let i = 0; i < count; i++) {
      const x = flatXyzIntensity[i * 4 + 0];
      const y = flatXyzIntensity[i * 4 + 1];
      const z = flatXyzIntensity[i * 4 + 2];
      const intensity = flatXyzIntensity[i * 4 + 3];

      // uklad lidaru: Z=gora; Three.js: Y=gora -> zamiana osi
      posAttr.array[i * 3 + 0] = x;
      posAttr.array[i * 3 + 1] = z;
      posAttr.array[i * 3 + 2] = y;

      const [r, g, b] = intensityToColor(intensity, minIntensity, maxIntensity);
      colorAttr.array[i * 3 + 0] = r;
      colorAttr.array[i * 3 + 1] = g;
      colorAttr.array[i * 3 + 2] = b;
    }

    posAttr.needsUpdate = true;
    colorAttr.needsUpdate = true;
    geometry.setDrawRange(0, count);
  }

  return { object: points, update };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { createPointCloud };
} else {
  window.createPointCloud = createPointCloud;
}
```

- [ ] **Step 2: Implement `viewer.js`** (scene, custom orbit camera, render loop)

```javascript
// gremlin/lidar_viewer/frontend/js/viewer.js
/**
 * Scena Three.js z wlasna (bez OrbitControls) sferyczna kamera orbitalna:
 * przeciaganie mysza = obrot, kolko = zoom. To swiadoma decyzja - CDN-owy
 * OrbitControls.js byl przyczyna awarii w prototypie (404, brak
 * czytelnego bledu w UI).
 */
function createViewer(canvas, maxPoints) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a0e17);

  const camera = new THREE.PerspectiveCamera(55, canvas.clientWidth / canvas.clientHeight, 0.01, 200);
  const cameraState = { radius: 4.5, theta: 0.9, phi: 1.15 };

  function updateCameraPosition() {
    const sinPhi = Math.sin(cameraState.phi);
    camera.position.set(
      cameraState.radius * sinPhi * Math.sin(cameraState.theta),
      cameraState.radius * Math.cos(cameraState.phi),
      cameraState.radius * sinPhi * Math.cos(cameraState.theta)
    );
    camera.lookAt(0, 0, 0);
  }
  updateCameraPosition();

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(canvas.clientWidth, canvas.clientHeight);

  let dragging = false;
  let lastX = 0;
  let lastY = 0;

  canvas.addEventListener('mousedown', (e) => { dragging = true; lastX = e.clientX; lastY = e.clientY; });
  window.addEventListener('mouseup', () => { dragging = false; });
  window.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    const dx = e.clientX - lastX;
    const dy = e.clientY - lastY;
    lastX = e.clientX;
    lastY = e.clientY;
    cameraState.theta -= dx * 0.005;
    cameraState.phi = Math.max(0.15, Math.min(Math.PI - 0.15, cameraState.phi - dy * 0.005));
    updateCameraPosition();
  });
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    cameraState.radius = Math.max(0.5, Math.min(30, cameraState.radius + e.deltaY * 0.003));
    updateCameraPosition();
  }, { passive: false });

  const grid = new THREE.GridHelper(10, 20, 0x2a3550, 0x1a2236);
  scene.add(grid);

  const cloud = createPointCloud(THREE, maxPoints);
  scene.add(cloud.object);

  function onResize() {
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
  }
  window.addEventListener('resize', onResize);

  function render() {
    requestAnimationFrame(render);
    renderer.render(scene, camera);
  }

  return {
    scene,
    camera,
    renderer,
    render,
    setPoints: (flatXyzIntensity, pointCount) => cloud.update(flatXyzIntensity, pointCount, intensityToColor),
  };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { createViewer };
} else {
  window.createViewer = createViewer;
}
```

- [ ] **Step 3: Implement `imu_panel.js`**

```javascript
// gremlin/lidar_viewer/frontend/js/imu_panel.js
function createImuPanel(containerEl) {
  function update({ quaternion, angularVelocity, linearAcceleration }) {
    containerEl.textContent =
      `quat [x,y,z,w] = [${Array.from(quaternion).map((v) => v.toFixed(3)).join(', ')}]\n` +
      `ang.vel = [${Array.from(angularVelocity).map((v) => v.toFixed(3)).join(', ')}]\n` +
      `lin.acc = [${Array.from(linearAcceleration).map((v) => v.toFixed(3)).join(', ')}]`;
  }
  return { update };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { createImuPanel };
} else {
  window.createImuPanel = createImuPanel;
}
```

- [ ] **Step 4: Implement `metrics_panel.js`**

```javascript
// gremlin/lidar_viewer/frontend/js/metrics_panel.js
function createMetricsPanel(containerEl) {
  let frameCount = 0;
  let lastFpsSample = performance.now();
  let renderFps = 0;

  function tickRenderFrame() {
    frameCount++;
    const now = performance.now();
    const elapsed = now - lastFpsSample;
    if (elapsed >= 1000) {
      renderFps = (frameCount * 1000) / elapsed;
      frameCount = 0;
      lastFpsSample = now;
    }
  }

  function updateFromServerMetrics({ fps, pointsInWindow, latencyMs }) {
    containerEl.textContent =
      `punkty: ${pointsInWindow} | scan FPS: ${fps.toFixed(1)} | render FPS: ${renderFps.toFixed(1)} | opoznienie: ${latencyMs.toFixed(1)}ms`;
  }

  return { tickRenderFrame, updateFromServerMetrics };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { createMetricsPanel };
} else {
  window.createMetricsPanel = createMetricsPanel;
}
```

- [ ] **Step 5: Implement `main.js`** (wires everything together on page load)

```javascript
// gremlin/lidar_viewer/frontend/js/main.js
window.addEventListener('DOMContentLoaded', () => {
  const canvas = document.getElementById('viewer-canvas');
  const imuEl = document.getElementById('imu-panel');
  const metricsEl = document.getElementById('metrics-panel');

  const MAX_POINTS = 200000; // gorny limit bufora - okno akumulacji jest po stronie backendu
  const viewer = createViewer(canvas, MAX_POINTS);
  const imuPanel = createImuPanel(imuEl);
  const metricsPanel = createMetricsPanel(metricsEl);

  const wsUrl = `ws://${window.location.hostname}:${window.location.port || 8080}`;
  window.wsClient.connect(wsUrl, {
    onScan: ({ points, pointCount }) => viewer.setPoints(points, pointCount),
    onImu: (imu) => imuPanel.update(imu),
    onMetrics: (metrics) => metricsPanel.updateFromServerMetrics(metrics),
  });

  function frame() {
    metricsPanel.tickRenderFrame();
    requestAnimationFrame(frame);
  }
  frame();

  viewer.render();
});
```

- [ ] **Step 6: Implement `index.html`**

```html
<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<title>LiDAR Viewer</title>
<link rel="stylesheet" href="css/style.css">
</head>
<body>
  <div id="panel">
    <h1>Unitree L1 - podglad na zywo</h1>
    <canvas id="viewer-canvas"></canvas>
    <pre id="imu-panel">brak danych IMU</pre>
    <pre id="metrics-panel">brak danych</pre>
  </div>

  <script src="js/vendor/three.min.js"></script>
  <script src="js/color.js"></script>
  <script src="js/ws_client.js"></script>
  <script src="js/pointcloud.js"></script>
  <script src="js/viewer.js"></script>
  <script src="js/imu_panel.js"></script>
  <script src="js/metrics_panel.js"></script>
  <script src="js/main.js"></script>
</body>
</html>
```

- [ ] **Step 7: Implement `css/style.css`**

```css
html, body {
  margin: 0;
  padding: 0;
  background: #0a0e17;
  color: #f4f6fb;
  font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
}

#panel {
  max-width: 1400px;
  margin: 24px auto;
}

#viewer-canvas {
  width: 100%;
  height: 640px;
  display: block;
  border-radius: 10px;
  background: #060911;
}

#imu-panel, #metrics-panel {
  font-size: 13px;
  color: #7d8aa3;
  white-space: pre-wrap;
}
```

- [ ] **Step 8: Manual verification (documented, not automated — no browser in this environment)**

1. Start the app in replay mode against a short synthetic recording (see
   Task 8's test helpers for how to build one, or wait for a real
   conversion in Task 12).
2. Open `frontend/index.html` in a browser pointed at
   `ws://localhost:8080`.
3. Confirm: point cloud renders and updates without flickering/resetting
   the camera; dragging rotates the view; the scroll wheel zooms; the IMU
   panel shows numbers; the metrics panel updates roughly once per
   second.
4. Record the result of this manual check in the task's commit message or
   PR description — this substitutes for an automated test here.

- [ ] **Step 9: Commit**

```bash
cd /home/gremlin/gremlin
git add lidar_viewer/frontend/js/viewer.js lidar_viewer/frontend/js/pointcloud.js \
        lidar_viewer/frontend/js/imu_panel.js lidar_viewer/frontend/js/metrics_panel.js \
        lidar_viewer/frontend/js/main.js lidar_viewer/frontend/index.html lidar_viewer/frontend/css/style.css
git commit -m "feat(lidar_viewer): Three.js viewer, custom orbit camera, IMU/metrics panels"
```

---

## Task 12: `tools/convert_bag.py` — one-time .bag conversion

**Files:**
- Create: `gremlin/lidar_viewer/tools/convert_bag.py`
- Test: `gremlin/lidar_viewer/tests/test_convert_bag.py`

**Interfaces:**
- Produces: `messages_to_recording(messages: Iterable[tuple[str, bytes, int]], output_path: str) -> int` — pure function, takes an already-extracted stream of `(topic, raw_bytes, timestamp_ns)` and writes it via `FrameRecorder`; returns the number of records written. This is the fully-testable half.
- Produces: `convert_bag(bag_path: str, output_path: str) -> int` — thin adapter using `rosbags.rosbag2.Reader` to extract `PointCloud2`/`Imu` messages, re-encode them into our own UDP-datagram-shaped bytes (matching `frame_parser`'s expected format so `--replay` can read the converted file identically to a live recording), and delegate to `messages_to_recording`. This half is **not** unit tested here (needs a real `.bag` + `rosbags`, neither available in this environment) — marked accordingly.
- Produces: CLI `python3 tools/convert_bag.py <input.bag> <output.bin>`

Design choice worth noting: rather than inventing a third data
representation, `convert_bag.py` re-encodes extracted `.bag` messages into
the *exact same* UDP-datagram byte layout `frame_parser.py` already
understands (msgType 101/102 + the same struct layouts) — so the
converted file plays back through `--replay` with zero special-casing.

- [ ] **Step 1: Write the failing test for the testable half**

```python
# gremlin/lidar_viewer/tests/test_convert_bag.py
import os
import struct
import tempfile

from tools.convert_bag import messages_to_recording
from backend.player import read_records


def test_messages_to_recording_writes_all_messages_in_order():
    messages = [
        ("/imu", b"\x01\x02", 1_000_000_000),
        ("/scan", b"\x03\x04\x05", 1_000_500_000),
    ]

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.bin")
        count = messages_to_recording(messages, path)

        assert count == 2
        records = list(read_records(path))
        assert records == [
            (1_000_000_000, b"\x01\x02"),
            (1_000_500_000, b"\x03\x04\x05"),
        ]


def test_messages_to_recording_empty_input_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.bin")
        count = messages_to_recording([], path)

        assert count == 0
        assert list(read_records(path)) == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /home/gremlin/gremlin/lidar_viewer && /home/gremlin/gremlin/.venv/bin/python3 -m pytest tests/test_convert_bag.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.convert_bag'`.

- [ ] **Step 3: Create `tools/__init__.py` and implement `convert_bag.py`**

```bash
touch /home/gremlin/gremlin/lidar_viewer/tools/__init__.py
```

```python
# gremlin/lidar_viewer/tools/convert_bag.py
"""
Jednorazowa konwersja istniejacego nagrania .bag do wlasnego formatu
recorder.py, zeby dalej mozna bylo je odtwarzac przez `--replay` dokladnie
tak samo jak nagranie live - bez trzymania zaleznosci od ROS/rosbags w
runtime glownej aplikacji.

Wymaga: pip install -r tools/requirements.txt (rosbags, czysty Python, bez
instalacji ROS).
"""

import argparse
import struct
import sys
from typing import Iterable, Tuple

sys.path.insert(0, __file__.rsplit("/", 2)[0])  # zeby "backend" bylo importowalne przy uruchamianiu jako skrypt

from backend.recorder import FrameRecorder  # noqa: E402

IMU_MSG_TYPE = 101
SCAN_MSG_TYPE = 102
_HEADER_FMT = "<II"


def _wrap_as_udp_datagram(msg_type: int, payload: bytes) -> bytes:
    header = struct.pack(_HEADER_FMT, msg_type, len(payload))
    return header + payload


def messages_to_recording(
    messages: Iterable[Tuple[str, bytes, int]], output_path: str
) -> int:
    """
    messages: iterowalne (topic, raw_datagram_bytes, timestamp_ns) - juz w
    formacie UDP-datagramu (naglowek+payload), gotowe do zapisu.
    Zwraca liczbe zapisanych rekordow.
    """
    count = 0
    with FrameRecorder(output_path) as recorder:
        for _topic, raw_bytes, timestamp_ns in messages:
            recorder.write(raw_bytes, timestamp_ns=timestamp_ns)
            count += 1
    return count


def convert_bag(bag_path: str, output_path: str) -> int:
    """
    Czyta .bag przez rosbags (bez ROS), ekstrahuje PointCloud2/Imu, koduje
    je jako te same bajty co live UDP z bridge'a (patrz frame_parser.py),
    i zapisuje przez messages_to_recording.

    UWAGA: ta funkcja wymaga realnego pliku .bag i biblioteki `rosbags` -
    nie jest pokryta testem jednostkowym w tym repo (brak obu w srodowisku
    deweloperskim tego zadania). Zweryfikuj recznie na wlasnym .bag po
    zainstalowaniu `pip install -r tools/requirements.txt`.
    """
    from rosbags.highlevel import AnyReader
    from pathlib import Path

    messages = []
    with AnyReader([Path(bag_path)]) as reader:
        for connection, timestamp_ns, rawdata in reader.messages():
            msg = reader.deserialize(rawdata, connection.msgtype)
            if connection.msgtype.endswith("Imu"):
                payload = struct.pack(
                    "<dI4f3f3f",
                    timestamp_ns / 1e9,
                    0,
                    msg.orientation.x, msg.orientation.y, msg.orientation.z, msg.orientation.w,
                    msg.angular_velocity.x, msg.angular_velocity.y, msg.angular_velocity.z,
                    msg.linear_acceleration.x, msg.linear_acceleration.y, msg.linear_acceleration.z,
                )
                messages.append(("imu", _wrap_as_udp_datagram(IMU_MSG_TYPE, payload), timestamp_ns))
            elif connection.msgtype.endswith("PointCloud2"):
                # PointCloud2 -> lista punktow (x,y,z,intensity) zalezy od
                # layoutu pol wiadomosci; do dopracowania recznie wzgledem
                # konkretnego .bag (nazwy pol moga sie roznic).
                pass  # celowo minimalne - patrz docstring, wymaga realnego .bag do weryfikacji

    return messages_to_recording(messages, output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Konwertuje .bag na format recorder.py")
    parser.add_argument("bag_path")
    parser.add_argument("output_path")
    args = parser.parse_args()

    count = convert_bag(args.bag_path, args.output_path)
    print(f"Zapisano {count} rekordow do {args.output_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /home/gremlin/gremlin/lidar_viewer && /home/gremlin/gremlin/.venv/bin/python3 -m pytest tests/test_convert_bag.py -v`
Expected: 2 passed. (Only the pure `messages_to_recording` path is tested — `convert_bag`'s PointCloud2 extraction is explicitly flagged in the docstring as needing manual verification against a real file, since its exact field layout depends on the specific `.bag`'s point field ordering.)

- [ ] **Step 5: Run the full backend test suite**

Run: `cd /home/gremlin/gremlin/lidar_viewer && /home/gremlin/gremlin/.venv/bin/python3 -m pytest tests/ -v`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
cd /home/gremlin/gremlin
git add lidar_viewer/tools/
git commit -m "feat(lidar_viewer): one-time .bag to recording-format converter"
```

---

## Task 13: Remove the old MAVLink/serial lidar pipeline from `gremlin`

**Files:**
- Delete: `src/hardware/lidar/unitree_l1.py`
- Delete: `src/workers/lidar_worker.py`
- Delete: `src/workers/slam_worker.py`
- Delete: `src/hardware/lidar/slam.py`
- Delete: `src/logic/mecanum_odometry.py`
- Delete: `site/public/tabs/lidar.js`
- Modify: `src/hardware/lidar/factory.py` (drop the `UnitreeL1Lidar` branch — see note below)
- Modify: `src/robot_controller.py` (drop `lidar_worker`/`slam_worker` wiring)
- Modify: `src/services/command_processor.py` (drop `get_lidar_points`/`get_slam_pose` handlers and their `_send_*` methods)
- Modify: `config.json` (drop `lidar`, `slam`, `drivetrain` keys — `drivetrain` was added solely for the old SLAM's odometry, per the spec)
- Modify: `site/public/index.html` (drop the `<script src="tabs/lidar.js">` tag and the LiDAR nav entry, if present)

**Interfaces:** none produced — this task only removes dead code and
updates the modules that referenced it. This is the last task, so nothing
downstream depends on what's removed here.

This task has no new tests of its own — its "test" is that the rest of
`gremlin` still imports and its existing test suite (if any) still passes
after the removal. `src/hardware/lidar/obstacle_reducer.py` is explicitly
**out of scope** — it's an independent prototype for a future L2 driver,
per the design spec.

- [ ] **Step 1: Confirm nothing outside the files being touched imports the modules slated for deletion**

```bash
cd /home/gremlin/gremlin
grep -rn "unitree_l1\|lidar_worker\|slam_worker\|hardware\.lidar\.slam\b\|mecanum_odometry" \
  --include="*.py" src/ | grep -v "src/hardware/lidar/obstacle_reducer.py"
grep -rn "tabs/lidar.js" site/public/
```

Review the output before proceeding — if something unexpected shows up
(an import this plan didn't anticipate), stop and re-scope this task
rather than deleting blindly.

- [ ] **Step 2: Delete the old backend files**

```bash
git rm src/hardware/lidar/unitree_l1.py
git rm src/workers/lidar_worker.py
git rm src/workers/slam_worker.py
git rm src/hardware/lidar/slam.py
git rm src/logic/mecanum_odometry.py
```

- [ ] **Step 3: Update `src/hardware/lidar/factory.py`**

Remove the `UnitreeL1Lidar` import and branch, leaving only the dummy
path (there is no real driver to fall back to anymore — the real lidar is
served by the new standalone `lidar_viewer` app instead):

```python
# gremlin/src/hardware/lidar/factory.py
from .interface import LidarInterface
from .dummy_lidar import DummyLidar


def create_lidar(config: dict) -> LidarInterface:
    # Prawdziwy odczyt lidaru zastapiony przez samodzielna aplikacje
    # lidar_viewer/ (patrz docs/superpowers/specs/2026-08-25-lidar-udp-viewer-design.md).
    # Ten factory zostaje dla kompatybilnosci z reszta robot_controller,
    # ktory nadal oczekuje jakiegos LidarInterface (np. pod przyszly
    # sterownik L2) - obecnie zawsze zwraca DummyLidar.
    return DummyLidar()
```

- [ ] **Step 4: Update `src/robot_controller.py`**

Remove the `LidarWorker`/`SlamWorker` imports, instantiations, and their
`start()`/`stop()` calls in `run()`. Read the current file first — the
exact line numbers shift as other changes land — and remove:
- `from .workers.lidar_worker import LidarWorker`
- `from .workers.slam_worker import SlamWorker`
- `self.lidar_worker = LidarWorker(...)` block
- `self.slam_worker = SlamWorker(...)` block
- `self.lidar_worker.start()` / `self.slam_worker.start()` in `run()`
- `await self.lidar_worker.stop()` / `await self.slam_worker.stop()` in the `finally` block

Leave the `lidar: LidarInterface` constructor parameter and
`self.sd_card`/other unrelated wiring untouched — `create_lidar()` still
needs to be called from `default.py` and passed in, it just now always
returns a `DummyLidar`.

- [ ] **Step 5: Update `src/services/command_processor.py`**

Remove the `get_lidar_points`/`get_slam_pose` branches in
`process_commands()` and the `_send_lidar_points`/`_send_slam_pose`
methods entirely (search for those exact strings — both the dispatch
branch and the method definition need to go).

- [ ] **Step 6: Update `config.json`**

Remove the `"lidar"`, `"slam"`, and `"drivetrain"` top-level keys. Verify
the result is still valid JSON:

```bash
python3 -c "import json; json.load(open('config.json')); print('JSON OK')"
```

- [ ] **Step 7: Update `site/public/index.html`**

Remove the `<script src="tabs/lidar.js"></script>` line and any nav
button/link that pointed at the LiDAR tab (search for `lidar` case-
insensitively in the file to find both).

- [ ] **Step 8: Verify the remaining Python still compiles**

```bash
cd /home/gremlin/gremlin
for f in src/hardware/lidar/factory.py src/robot_controller.py src/services/command_processor.py src/default.py; do
  python3 -c "compile(open('$f').read(), '$f', 'exec')" && echo "OK: $f" || echo "FAIL: $f"
done
```

Expected: `OK` for all four files.

- [ ] **Step 9: Verify the frontend JS still parses**

```bash
node --check /home/gremlin/gremlin/site/public/app.js
```

Expected: no output (success).

- [ ] **Step 10: Commit**

```bash
cd /home/gremlin/gremlin
git add -A src/ site/ config.json
git commit -m "refactor: remove MAVLink/serial lidar pipeline, superseded by standalone lidar_viewer app"
```

---

## Self-Review Notes

**Spec coverage:**
- Live UDP receive + Scan/IMU parsing → Tasks 2, 6, 8.
- Live point-cloud rendering with in-place geometry updates → Tasks 10, 11.
- Intensity-based coloring with auto-normalization → Tasks 10 (`color.js`), 11 (`pointcloud.js`).
- IMU panel → Task 11 (`imu_panel.js`).
- Point count / FPS / latency metrics → Tasks 7 (`encode_metrics_frame`), 8 (`metrics_loop`), 11 (`metrics_panel.js`).
- Custom camera controls, no CDN `OrbitControls` → Task 11 (`viewer.js`), Task 9 (vendored Three.js).
- Range-based noise filtering, configurable → Task 3 (`accumulator.py`'s `max_range_m`), exposed via Task 8's `--max-range-m` CLI flag.
- Recording + replay for testing without hardware → Task 4 (`recorder.py`/`player.py`), Task 8 (`--record`/`--replay`).
- `.bag` conversion path → Task 12.
- Migration/removal of the old pipeline → Task 13.

**Placeholder scan:** no "TBD"/"implement later" left; the one spot with
reduced test coverage (`convert_bag.py`'s `PointCloud2` extraction) is
explicitly justified (no real `.bag` file or `rosbags` install available
in this environment) rather than silently glossed over, and its pure
counterpart (`messages_to_recording`) is fully tested.

**Type/interface consistency check:** `ScanFrame.points` tuples are
`(x, y, z, intensity, time, ring)` consistently from Task 2 through Task 8
(`accumulator.add_scan` unpacks exactly that 6-tuple shape). WS wire
format (`encode_scan_frame`/`encode_imu_frame` in Task 7) matches
`ws_client.js`'s `decodeMessage` byte offsets exactly (verified by the
mirrored Node tests in Task 10, which hand-construct buffers the same way
Task 7's Python encoder does). `BridgeManager` constructor signature is
identical between Task 5's implementation and Task 8's `_run_live` call
site.
