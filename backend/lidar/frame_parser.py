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
    if valid_points_num > POINTS_PER_SCAN:
        raise FrameParseError(
            f"validPointsNum {valid_points_num} exceeds POINTS_PER_SCAN {POINTS_PER_SCAN}"
        )

    points = []
    offset = _SCAN_PREFIX_LEN
    for _ in range(valid_points_num):
        x, y, z, intensity, t, ring = struct.unpack(
            _POINT_FMT, payload[offset:offset + _POINT_LEN]
        )
        points.append((x, y, z, intensity, t, ring))
        offset += _POINT_LEN

    return ScanFrame(stamp, msg_id, points)
