# ESP LiDAR obstacle visualization

## Goal

Receive obstacle messages emitted by the ESP LiDAR protocol and display each detected obstacle in the ESP LiDAR viewer as a red, semi-transparent 3D box.

## Protocol

The UDP receiver already accepts the common 32-byte `LIDR` header. Add support for message type `3` (`OBSTACLES`). The type-3 header fields are:

- `id_value`: source cloud `frame_id`
- `field12`: obstacle `packet_id`
- `field14`: obstacle `packet_count`
- `field16`: obstacle count in the datagram
- `field18`: total obstacle count for the frame
- `timestamp_us`: source cloud timestamp

Each obstacle record is 32 bytes, little-endian:

`center_x`, `center_y`, `center_z`, `size_x`, `size_y`, `size_z`, `nearest_distance_m` as float32, followed by `point_count` and `flags` as uint16.

The parser must reject truncated records and invalid packet counts without interrupting the UDP service. Unknown message types remain ignored. A valid zero-obstacle frame must be propagated so the frontend clears stale boxes.

## Data flow

1. `backend/esp_lidar/frame_parser.py` decodes type-3 datagrams into a typed obstacle packet.
2. `backend/esp_lidar/http_api.py` collects obstacle packets by source frame and waits for the complete packet set.
3. The service broadcasts a WebSocket obstacle message using the existing obstacle message format and client registry.
4. The ESP LiDAR tab handles obstacle updates independently of point-cloud updates.
5. The viewer replaces the previous obstacle group with boxes for the newest complete frame.

## Rendering

Each obstacle is rendered as a red, semi-transparent `THREE.Mesh` using the decoded center and bounding-box size. The obstacle group is attached to the same transformed scene branch as the point cloud, so manual tilt and IMU orientation apply identically to both. Empty obstacle frames remove all existing boxes.

The box dimensions must remain positive and finite before creating geometry. Invalid records are ignored at the parser boundary or rejected as a malformed datagram, consistent with the existing UDP error handling.

## Testing

- Decode one valid type-3 datagram, including all fields and a zero-obstacle datagram.
- Reject a truncated type-3 datagram and a zero packet count.
- Verify that multiple obstacle datagrams produce one complete frame and that an incomplete frame is not broadcast.
- Verify that the frontend creates a red box with the expected transformed center and dimensions, then clears it for an empty frame.
- Run the focused backend and frontend test suites plus the existing application tests relevant to the ESP LiDAR service.

## Scope

This change does not alter ESP firmware, obstacle detection thresholds, point-cloud processing, IMU decoding, or the existing Unitree LiDAR tab.