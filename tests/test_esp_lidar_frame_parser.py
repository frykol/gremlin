import struct

import pytest

from backend.esp_lidar.frame_parser import (
    FrameParseError,
    ObstaclePacket,
    decode_packet,
)


HEADER_FMT = "<4sBBHIHHHHQI"
OBSTACLE_FMT = "<7fHH"


def make_obstacle_datagram(
    frame_id, packet_id, packet_count, total_obstacles, obstacles, truncate=False
):
    header = struct.pack(
        HEADER_FMT,
        b"LIDR",
        1,
        3,
        32,
        frame_id,
        packet_id,
        packet_count,
        len(obstacles),
        total_obstacles,
        123456,
        0,
    )
    payload = b"".join(struct.pack(OBSTACLE_FMT, *record) for record in obstacles)
    if truncate:
        payload = payload[:-1]
    return header + payload


def test_decode_obstacle_packet():
    data = make_obstacle_datagram(
        17, 0, 1, 1, [(1.0, 2.0, 0.5, 0.4, 0.6, 1.2, 1.1, 12, 3)]
    )

    packet = decode_packet(data)

    assert isinstance(packet, ObstaclePacket)
    assert packet.frame_id == 17
    assert packet.obstacles[0].center_x == 1.0
    assert packet.obstacles[0].size_z == pytest.approx(1.2)
    assert packet.obstacles[0].point_count == 12
    assert packet.obstacles[0].flags == 3


def test_decode_empty_obstacle_frame():
    packet = decode_packet(make_obstacle_datagram(18, 0, 1, 0, []))

    assert isinstance(packet, ObstaclePacket)
    assert packet.obstacles == []


def test_decode_obstacle_packet_rejects_bad_datagrams():
    with pytest.raises(FrameParseError):
        decode_packet(
            make_obstacle_datagram(
                19, 0, 1, 1, [(1.0, 2.0, 0.5, 0.4, 0.6, 1.2, 1.1, 12, 3)], True
            )
        )

    with pytest.raises(FrameParseError):
        decode_packet(make_obstacle_datagram(20, 0, 0, 0, []))