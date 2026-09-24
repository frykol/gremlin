# ESP LiDAR control from the web tab

## Goal

Expose every command from `esp_rasp_test/CONTROL_PROTOCOL.txt` in the existing
ESP LiDAR tab, without changing the binary protocol or the existing scan,
obstacle, IMU, and metrics streams.

## Architecture

The Python `backend.esp_lidar` service owns the control connection because it
already receives ESP LiDAR traffic and runs on the Raspberry Pi. A new small
control client will encode `COMMAND` packets, send them to UDP port 5006,
validate matching `COMMAND_ACK` packets, and retry timed-out requests. The ESP
address and control port will be configurable, defaulting to `192.168.50.10`
and `5006`.

The HTTP service will expose `POST /api/esp_lidar/command`. Its JSON body will
contain a command name and up to four integer arguments. The response will
contain the decoded ACK state: result code, active flags, stream mask, command
counter, uptime, and request metadata. A convenience `GET
/api/esp_lidar/status` endpoint will issue `GET_STATUS`. CORS will allow POST in
addition to the existing GET/OPTIONS methods.

## Web UI

The ESP LiDAR tab will add a compact control panel next to the existing viewer:

- refreshable status for LiDAR and fusion;
- independent cloud, IMU, and obstacles toggles;
- a stream-mask selector with all, none, or individual streams;
- ping, status refresh, and clear-history actions;
- visible pending and error states for unavailable ESP or rejected commands.

Every UI action will call the HTTP service and update the displayed state from
the ACK rather than assuming that the requested value was accepted. Viewer and
WebSocket behavior remain unchanged.

## Error handling

Malformed command input returns HTTP 400. Unsupported command names and invalid
arguments are rejected before sending. UDP timeout or socket errors return an
appropriate HTTP 502 response. ESP result codes are returned as data with a
non-success command status so the UI can show the actual rejection reason.

## Testing

Python tests will cover exact command frame encoding, ACK validation including
request-id matching, retry/timeout behavior, and HTTP command/status responses
using an injected fake transport. Node tests will verify that the tab exposes
the control markup and command endpoint contract. Existing streaming tests and
behavior remain unchanged.