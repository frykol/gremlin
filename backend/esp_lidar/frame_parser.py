"""
Parsowanie datagramow UDP z ESP32P4 (protokol LIDR UDP v1, patrz
esp_rasp_test/PROTOCOL.txt).

Wspolny 32-bajtowy naglowek ma 4 pola "message-specific" (offsety 8, 12,
14, 16, 18), ktorych znaczenie zalezy od message type:

  type 1 (POINT_CLOUD): frame_id(4B) / packet_id(2B) / packet_count(2B) /
                         point_count(2B) / total_point_count(2B)
  type 2 (IMU):         sample_id(4B) / unitree_packet_id(2B) / 0(2B) /
                         imu_payload_size=40(2B) / 0(2B)

Dla point cloud parser zwraca identyfikatory frame_id/packet_id/packet_count,
aby warstwa wyzej mogla zlozyc kompletna ramke przed jej wyslaniem do WS.

Format payloadu IMU (quaternion + angular_velocity + linear_acceleration)
jest CELOWO identyczny jak backend/lidar/frame_parser.py (Unitree L1) -
zrodlo danych to ten sam Unitree IMU MAVLink packet, tylko relayowany
przez ESP zamiast bezposrednio przez bridge/serial. Dzieki temu backend
moze uzyc GOTOWEGO backend/lidar/ws_server.encode_imu_frame(...) bez
przepisywania kodowania, a frontend GOTOWEGO dekodera w
site/public/lidar/js/ws_client.js (ten sam ukland: 10 floatow, x,y,z,w).
"""

import struct
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

MAGIC = b"LIDR"
VERSION = 1
MSG_POINT_CLOUD = 1
MSG_IMU = 2
MSG_OBSTACLES = 3

_HEADER_FMT = "<4sBBHIHHHHQI"
_HEADER_LEN = struct.calcsize(_HEADER_FMT)  # 32

_POINT_FMT = "<fffBBH"
_POINT_LEN = struct.calcsize(_POINT_FMT)  # 16

_IMU_FMT = "<4f3f3f"  # quaternion[4], angular_velocity[3], linear_acceleration[3]
_IMU_LEN = struct.calcsize(_IMU_FMT)  # 40

_OBSTACLE_FMT = "<7fHH"
_OBSTACLE_LEN = struct.calcsize(_OBSTACLE_FMT)  # 32


class FrameParseError(ValueError):
    """Pakiet uszkodzony, nieznany lub niezgodny z protokolem."""


@dataclass
class PointPacket:
    frame_id: int
    packet_id: int
    packet_count: int
    timestamp_us: int
    points: List[Tuple[float, float, float, int]]  # x, y, z, intensity


@dataclass
class ImuPacket:
    sample_id: int
    timestamp_us: int
    quaternion: Tuple[float, float, float, float]  # x, y, z, w
    angular_velocity: Tuple[float, float, float]
    linear_acceleration: Tuple[float, float, float]


@dataclass
class ObstacleRecord:
    center_x: float
    center_y: float
    center_z: float
    size_x: float
    size_y: float
    size_z: float
    nearest_distance_m: float
    point_count: int
    flags: int


@dataclass
class ObstaclePacket:
    frame_id: int
    packet_id: int
    packet_count: int
    total_obstacle_count: int
    timestamp_us: int
    obstacles: List[ObstacleRecord]


def decode_packet(
    data: bytes,
) -> Optional[Union[PointPacket, ImuPacket, ObstaclePacket]]:
    if len(data) < _HEADER_LEN:
        raise FrameParseError(f"datagram too short for header: {len(data)} bytes")

    (
        magic,
        version,
        message_type,
        header_size,
        msg_specific_id,
        field_12,
        field_14,
        field_16,
        _field_18,
        timestamp_us,
        _reserved,
    ) = struct.unpack(_HEADER_FMT, data[:_HEADER_LEN])

    if magic != MAGIC:
        raise FrameParseError(f"bad magic: {magic!r}")
    if version != VERSION:
        raise FrameParseError(f"unsupported version: {version}")
    if header_size != _HEADER_LEN:
        raise FrameParseError(f"unexpected header size: {header_size}")

    if message_type == MSG_IMU:
        imu_payload_size = field_16
        if imu_payload_size != _IMU_LEN:
            raise FrameParseError(
                f"unexpected IMU payload size: {imu_payload_size} != {_IMU_LEN}"
            )
        if len(data) < _HEADER_LEN + _IMU_LEN:
            raise FrameParseError(
                f"IMU payload too short: {len(data)} < {_HEADER_LEN + _IMU_LEN}"
            )
        values = struct.unpack(_IMU_FMT, data[_HEADER_LEN:_HEADER_LEN + _IMU_LEN])
        return ImuPacket(
            sample_id=msg_specific_id,
            timestamp_us=timestamp_us,
            quaternion=tuple(values[0:4]),
            angular_velocity=tuple(values[4:7]),
            linear_acceleration=tuple(values[7:10]),
        )

    if message_type == MSG_OBSTACLES:
        packet_count = field_14
        obstacle_count = field_16
        if packet_count == 0:
            raise FrameParseError("packet_count == 0")

        expected_len = _HEADER_LEN + obstacle_count * _OBSTACLE_LEN
        if len(data) < expected_len:
            raise FrameParseError(
                f"declared obstacle_count {obstacle_count} exceeds datagram size "
                f"{len(data)}"
            )

        obstacles = []
        offset = _HEADER_LEN
        for _ in range(obstacle_count):
            values = struct.unpack(
                _OBSTACLE_FMT, data[offset:offset + _OBSTACLE_LEN]
            )
            obstacles.append(ObstacleRecord(*values))
            offset += _OBSTACLE_LEN

        return ObstaclePacket(
            frame_id=msg_specific_id,
            packet_id=field_12,
            packet_count=packet_count,
            total_obstacle_count=_field_18,
            timestamp_us=timestamp_us,
            obstacles=obstacles,
        )

    if message_type != MSG_POINT_CLOUD:
        # Nieznany typ (protokol mogl urosnac) - nic do zrobienia.
        return None

    frame_id = msg_specific_id
    packet_id = field_12
    packet_count = field_14
    point_count = field_16
    if packet_count == 0:
        raise FrameParseError("packet_count == 0")

    expected_len = _HEADER_LEN + point_count * _POINT_LEN
    if len(data) < expected_len:
        raise FrameParseError(
            f"declared point_count {point_count} exceeds datagram size {len(data)}"
        )

    points = []
    offset = _HEADER_LEN
    for _ in range(point_count):
        x, y, z, intensity, _flags, _reserved = struct.unpack(
            _POINT_FMT, data[offset:offset + _POINT_LEN]
        )
        points.append((x, y, z, intensity))
        offset += _POINT_LEN

    return PointPacket(
        frame_id=frame_id,
        packet_id=packet_id,
        packet_count=packet_count,
        timestamp_us=timestamp_us,
        points=points,
    )
