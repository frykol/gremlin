import struct

import pytest

from backend.esp_lidar.control import (
    ACK_PAYLOAD,
    HEADER,
    MSG_COMMAND,
    MSG_COMMAND_ACK,
    EspControlClient,
    decode_ack,
    encode_command,
)


def make_ack(request_id, command_id, result, state_flags, stream_mask, command_count, uptime_ms):
    header = HEADER.pack(
        b"LIDR",
        1,
        MSG_COMMAND_ACK,
        32,
        request_id,
        command_id,
        result,
        ACK_PAYLOAD.size,
        0,
        123,
        0,
    )
    return header + ACK_PAYLOAD.pack(state_flags, stream_mask, command_count, uptime_ms)


def test_encode_command_matches_control_protocol():
    packet = encode_command(0x10203040, 3, (1,))

    assert len(packet) == 48
    assert packet[:4] == b"LIDR"
    assert struct.unpack_from("<BBH", packet, 4) == (1, MSG_COMMAND, 32)
    assert struct.unpack_from("<IHHHHQI", packet, 8) == (
        0x10203040,
        3,
        0,
        16,
        0,
        0,
        0,
    )
    assert struct.unpack_from("<IIII", packet, 32) == (1, 0, 0, 0)


def test_decode_ack_rejects_wrong_request_id():
    packet = make_ack(7, 2, 0, 3, 7, 9, 100)

    assert decode_ack(packet, expected_request_id=8) is None


def test_decode_ack_returns_status_fields():
    packet = make_ack(7, 2, 0, 3, 7, 9, 100)

    assert decode_ack(packet, expected_request_id=7) == {
        "request_id": 7,
        "command_id": 2,
        "result": 0,
        "timestamp_us": 123,
        "lidar_active": True,
        "fusion_enabled": True,
        "stream_mask": 7,
        "command_count": 9,
        "uptime_ms": 100,
    }


class FakeSocket:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.send_count = 0
        self.timeout = None

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendto(self, packet, address):
        self.send_count += 1

    def recvfrom(self, size):
        response = next(self.responses)
        if isinstance(response, BaseException):
            raise response
        return response, ("esp", 5006)

    def close(self):
        pass


def test_client_retries_and_returns_decoded_ack(monkeypatch):
    request_id = 7
    ack = make_ack(request_id, 2, 0, 1, 1, 2, 300)
    fake_socket = FakeSocket([socket_timeout(), ack])
    monkeypatch.setattr("backend.esp_lidar.control.make_request_id", lambda: request_id)

    client = EspControlClient("esp", 5006, socket_factory=lambda *_: fake_socket)

    assert client.send(2, ()) ["result"] == 0
    assert fake_socket.send_count == 2


def socket_timeout():
    return TimeoutError()