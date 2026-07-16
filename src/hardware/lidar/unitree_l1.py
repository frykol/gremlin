import math
import struct
from typing import List, Tuple

import serial

from .interface import LidarInterface

MAGIC = 0xFD
CRC_EXTRA = {16: 74, 17: 99}
DIST_FMT = "<HHH240s"
DIST_LEN = struct.calcsize(DIST_FMT)
AUX_FMT = "<5I16f2HB120s"
AUX_LEN = struct.calcsize(AUX_FMT)
POINTS_PER_SCAN = 120
MAX_RANGE_M = 30.0


def _crc16_x25(data: bytes, crc: int = 0xFFFF) -> int:
    for byte in data:
        tmp = byte ^ (crc & 0xFF)
        tmp = (tmp ^ (tmp << 4)) & 0xFF
        crc = ((crc >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4)) & 0xFFFF
    return crc


def _iter_mavlink_frames(buf: bytearray):
    frames = []
    i = 0
    n = len(buf)
    while i < n:
        if buf[i] != MAGIC:
            i += 1
            continue
        if n - i < 10:
            break
        payload_len = buf[i + 1]
        incompat_flags = buf[i + 2]
        msgid = buf[i + 7] | (buf[i + 8] << 8) | (buf[i + 9] << 16)
        signed = bool(incompat_flags & 0x01)
        total_len = 10 + payload_len + 2 + (13 if signed else 0)
        if n - i < total_len:
            break

        crc_span = bytes(buf[i + 1: i + 10 + payload_len])
        crc = _crc16_x25(crc_span)
        crc = _crc16_x25(bytes([CRC_EXTRA.get(msgid, 0)]), crc)
        crc_received = buf[i + 10 + payload_len] | (buf[i + 10 + payload_len + 1] << 8)

        if crc == crc_received:
            payload = bytes(buf[i + 10: i + 10 + payload_len])
            frames.append((msgid, payload))
            i += total_len
        else:
            i += 1

    return frames, buf[i:]


def _parse_distance_packet(payload: bytes) -> dict:
    packet_id, packet_cnt, payload_size, point_data = struct.unpack(DIST_FMT, payload)
    ranges = struct.unpack("<120H", point_data)
    return {"packet_id": packet_id, "ranges": ranges}


def _parse_auxiliary_packet(payload: bytes) -> dict:
    (lidar_sync_delay_time, time_stamp_s_step, time_stamp_us_step,
     sys_rotation_period, com_rotation_period,
     com_horizontal_angle_start, com_horizontal_angle_step,
     sys_vertical_angle_start, sys_vertical_angle_span,
     apd_temperature, dirty_index, imu_temperature,
     up_optical_q, down_optical_q, apd_voltage,
     imu_angle_x_offset, imu_angle_y_offset, imu_angle_z_offset,
     b_axis_dist, theta_angle, ksi_angle,
     packet_id, payload_size,
     lidar_work_status, reflect_data) = struct.unpack(AUX_FMT, payload)

    return {
        "packet_id": packet_id,
        "com_horizontal_angle_start": com_horizontal_angle_start,
        "com_horizontal_angle_step": com_horizontal_angle_step,
        "sys_vertical_angle_start": sys_vertical_angle_start,
        "sys_vertical_angle_span": sys_vertical_angle_span,
        "b_axis_dist": b_axis_dist,
        "theta_angle": theta_angle,
        "ksi_angle": ksi_angle,
        "reflect_data": reflect_data,
    }


def _range_aux_to_cloud(aux: dict, dist: dict) -> List[Tuple[float, float, float]]:
    if aux["packet_id"] != dist["packet_id"]:
        return []

    range_scale = 0.001
    z_bias = 0.0445
    bias_laser_beam = aux["b_axis_dist"] / 1000

    sin_theta = math.sin(aux["theta_angle"])
    cos_theta = math.cos(aux["theta_angle"])
    sin_ksi = math.sin(aux["ksi_angle"])
    cos_ksi = math.cos(aux["ksi_angle"])

    pitch_cur = aux["sys_vertical_angle_start"] * math.pi / 180.0
    pitch_step = aux["sys_vertical_angle_span"] * math.pi / 180.0
    yaw_cur = aux["com_horizontal_angle_start"] * math.pi / 180.0
    yaw_step = aux["com_horizontal_angle_step"] / POINTS_PER_SCAN * math.pi / 180.0

    points: List[Tuple[float, float, float]] = []
    for j in range(POINTS_PER_SCAN):
        r = dist["ranges"][j]
        # r == 0: brak echa. r >= 0xFFFF: sentinel producenta (poza zasiegiem/nasycenie).
        if 0 < r < 0xFFFF and r * range_scale <= MAX_RANGE_M:
            range_float = range_scale * r
            sin_alpha, cos_alpha = math.sin(pitch_cur), math.cos(pitch_cur)
            sin_beta, cos_beta = math.sin(yaw_cur), math.cos(yaw_cur)

            A = (-cos_theta * sin_ksi + sin_theta * sin_alpha * cos_ksi) * range_float + bias_laser_beam
            B = cos_alpha * cos_ksi * range_float

            x = cos_beta * A - sin_beta * B
            y = sin_beta * A + cos_beta * B
            z = (sin_theta * sin_ksi + cos_theta * sin_alpha * cos_ksi) * range_float + z_bias
            points.append((x, y, z))

        pitch_cur += pitch_step
        yaw_cur += yaw_step

    return points


class UnitreeL1Lidar(LidarInterface):
    """Odczyt Unitree LiDAR L1 po porcie szeregowym (ramki MAVLink)."""

    def __init__(self, port: str = "/dev/ttyUSB0", baud: int = 2_000_000):
        self.port = port
        self.baud = baud

        self._ser: serial.Serial | None = None
        self._buf = bytearray()
        self._pending_dist: dict = {}
        self._pending_aux: dict = {}

    def start(self) -> None:
        if self._ser is not None:
            return
        self._ser = serial.Serial(self.port, self.baud, timeout=0)

    def stop(self) -> None:
        if self._ser is not None:
            self._ser.close()
            self._ser = None
        self._buf = bytearray()
        self._pending_dist.clear()
        self._pending_aux.clear()

    def read_points(self) -> List[Tuple[float, float, float]]:
        if self._ser is None:
            return []

        chunk = self._ser.read(1024 * 64)
        if not chunk:
            return []

        self._buf.extend(chunk)
        frames, self._buf = _iter_mavlink_frames(self._buf)

        points: List[Tuple[float, float, float]] = []
        for msgid, payload in frames:
            pid = None
            if msgid == 16 and len(payload) == DIST_LEN:
                d = _parse_distance_packet(payload)
                self._pending_dist[d["packet_id"]] = d
                pid = d["packet_id"]
            elif msgid == 17 and len(payload) == AUX_LEN:
                a = _parse_auxiliary_packet(payload)
                self._pending_aux[a["packet_id"]] = a
                pid = a["packet_id"]

            if pid is not None and pid in self._pending_dist and pid in self._pending_aux:
                points.extend(
                    _range_aux_to_cloud(self._pending_aux.pop(pid), self._pending_dist.pop(pid))
                )

        return points
