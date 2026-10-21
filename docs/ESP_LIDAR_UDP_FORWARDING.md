# ESP LiDAR UDP forwarding

The ESP LiDAR service on Raspberry Pi can optionally forward each completed
point-cloud snapshot to a Node.js process over UDP. UDP is connectionless: the
Node.js process binds a port and waits for datagrams, while the Raspberry Pi
sends datagrams to the Node.js host and port. The existing ESP-to-Pi UDP input
and the browser WebSocket stream are unchanged.

## Configure the Raspberry Pi

Set the destination to an address reachable from the Raspberry Pi in
`config.json`:

```json
"esp_lidar": {
  "ws_port": 8769,
  "udp_port": 5005,
  "forward_host": "192.168.1.50",
  "forward_port": 5010,
  "max_datagram_size": 1400
}
```

Use the Node server's LAN address for a same-network receiver, or its public
address for a server reachable over the internet. An empty `forward_host`
disables forwarding. Allow inbound UDP on `forward_port` in the receiver's
firewall/security group. For a receiver behind a router, configure UDP port
forwarding as well. Restart the Gremlin service after changing the config.

Each newly completed point-cloud frame is forwarded once. The existing browser
WebSocket continues to broadcast its latest scan at its normal cadence
(normally about 20 times per second). Only point clouds are forwarded; IMU and
obstacle messages are not. If the receiver is offline,
the Raspberry Pi continues its normal local stream. UDP does not retry or
guarantee delivery, so the receiver should discard incomplete frames. The
default datagram size is 1400 bytes to usually fit within an Ethernet MTU
without IP fragmentation.

## Datagram format

Every datagram starts with a 20-byte little-endian header, followed by zero or
more 16-byte point records. Each point record is four little-endian float32
values in this order: `x` metres, `y` metres, `z` metres, and `intensity`.
Flags from the ESP input protocol are not included, matching the current
browser scan stream.

| Offset | Size | Field |
| --- | ---: | --- |
| 0 | 4 | ASCII magic `ELDP` |
| 4 | 1 | Version, currently `1` |
| 5 | 1 | Message type, `1` = point cloud |
| 6 | 2 | Header size, `20` |
| 8 | 4 | Frame ID (`uint32`) |
| 12 | 2 | Chunk index, zero-based (`uint16`) |
| 14 | 2 | Chunk count (`uint16`) |
| 16 | 4 | Total points in the complete frame (`uint32`) |
| 20 | variable | Point records, 16 bytes each |

All integer and float fields are little-endian. The chunk count is at least 1;
an empty scan has one datagram with zero point records. Receivers should group
by frame ID, verify that the chunk count and total point count agree across a
frame, ignore duplicate chunk indexes, and discard frames that are incomplete
after a short timeout. Frame IDs wrap at 32 bits; do not use a frame ID alone
as a permanent unique identifier.

## Node.js receiver example

This example uses only Node's built-in `dgram` module. On a complete frame it
reconstructs the exact binary scan payload sent to the current browser
WebSocket: a little-endian `uint32` message type (`1`), a little-endian
`uint32` point count, then four float32 values per point. The payload can be
decoded with the same layout as `site/public/lidar/js/ws_client.js`.

```js
const dgram = require('node:dgram');

const PORT = 5010;
const HEADER_BYTES = 20;
const POINT_BYTES = 16;
const FRAME_TIMEOUT_MS = 500;
const MAX_IN_FLIGHT_FRAMES = 8;
const MAX_FRAME_BYTES = 1024 * 1024;
const frames = new Map();
const socket = dgram.createSocket('udp4');

function discardFrame(frameId) {
  const frame = frames.get(frameId);
  if (!frame) return;
  clearTimeout(frame.timeout);
  frames.delete(frameId);
}

socket.on('message', (message, remote) => {
  if (message.length < HEADER_BYTES || message.toString('ascii', 0, 4) !== 'ELDP') return;

  const version = message.readUInt8(4);
  const type = message.readUInt8(5);
  const headerBytes = message.readUInt16LE(6);
  const frameId = message.readUInt32LE(8);
  const chunkIndex = message.readUInt16LE(12);
  const chunkCount = message.readUInt16LE(14);
  const totalPoints = message.readUInt32LE(16);
  const payload = message.subarray(HEADER_BYTES);

  if (version !== 1 || type !== 1 || headerBytes !== HEADER_BYTES) return;
  if (chunkCount === 0 || chunkIndex >= chunkCount || payload.length % POINT_BYTES !== 0) return;
  if (totalPoints * POINT_BYTES > MAX_FRAME_BYTES || payload.length > 1400 - HEADER_BYTES) return;

  let frame = frames.get(frameId);
  if (!frame) {
    if (frames.size >= MAX_IN_FLIGHT_FRAMES) {
      discardFrame(frames.keys().next().value);
    }
    frame = {
      chunkCount,
      totalPoints,
      chunks: new Map(),
      receivedPoints: 0,
      timeout: setTimeout(() => discardFrame(frameId), FRAME_TIMEOUT_MS),
    };
    frames.set(frameId, frame);
  }

  if (frame.chunkCount !== chunkCount || frame.totalPoints !== totalPoints) {
    discardFrame(frameId);
    return;
  }
  if (frame.chunks.has(chunkIndex)) return;
  const chunkPoints = payload.length / POINT_BYTES;
  if (frame.receivedPoints + chunkPoints > frame.totalPoints) {
    discardFrame(frameId);
    return;
  }

  frame.chunks.set(chunkIndex, Buffer.from(payload));
  frame.receivedPoints += chunkPoints;
  if (frame.chunks.size !== frame.chunkCount) return;

  const pointBytes = Buffer.concat(
    Array.from({ length: frame.chunkCount }, (_, index) => frame.chunks.get(index))
  );
  if (frame.receivedPoints !== frame.totalPoints || pointBytes.length !== frame.totalPoints * POINT_BYTES) {
    discardFrame(frameId);
    return;
  }

  const websocketScanFrame = Buffer.allocUnsafe(8 + pointBytes.length);
  websocketScanFrame.writeUInt32LE(1, 0);
  websocketScanFrame.writeUInt32LE(frame.totalPoints, 4);
  pointBytes.copy(websocketScanFrame, 8);
  discardFrame(frameId);

  console.log(`Complete LiDAR frame ${frameId}: ${frame.totalPoints} points from ${remote.address}`);
  // websocketScanFrame is now in the same binary format as the Pi's browser WS scan.
});

socket.bind(PORT, '0.0.0.0', () => {
  console.log(`Waiting for ESP LiDAR UDP datagrams on :${PORT}`);
});
```

To read points from `websocketScanFrame`, read the count at byte offset 4 and
interpret the float data starting at offset 8 as groups of four values
`x, y, z, intensity`. For example, after checking the buffer length:

```js
const pointCount = websocketScanFrame.readUInt32LE(4);
const pointValues = new Float32Array(
  websocketScanFrame.buffer,
  websocketScanFrame.byteOffset + 8,
  pointCount * 4
);
```

Do not expose an unauthenticated UDP port to the public internet unless that is
intentional. UDP source addresses can be spoofed, and anyone able to reach the
port can send data to the receiver; restrict the source with firewall rules or
use a private network/VPN when appropriate.