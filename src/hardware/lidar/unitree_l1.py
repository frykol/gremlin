import math
import struct
from typing import List, Tuple

import serial

from .interface import LidarInterface

MAGIC = 0xFD
CRC_EXTRA = {16: 74, 17: 99, 19: 110, 14: 84}
# mavlink_msg_config_lidar_working_mode.h: msgid=14, payload=1B (request_type).
WORK_MODE_MSGID = 14
WORK_MODE_NORMAL = 1
WORK_MODE_STANDBY = 2
DIST_FMT = "<HHH240s"
DIST_LEN = struct.calcsize(DIST_FMT)
AUX_FMT = "<5I16f2HB120s"
AUX_LEN = struct.calcsize(AUX_FMT)
# mavlink_ret_imu_attitude_data_packet_t: quaternion[4] + angular_velocity[3]
# + linear_acceleration[3] (float32) + packet_id (uint16) = 42 bajtow.
IMU_FMT = "<10fH"
IMU_LEN = struct.calcsize(IMU_FMT)
POINTS_PER_SCAN = 120
MAX_RANGE_M = 30.0
MIN_RANGE_M = 0.05  # odrzuca szum przy obudowie lidara (za blisko czujnika)
MAX_INTENSITY = 255  # domyslnie brak filtra - odrzucaj punkty o odbiciu > tego progu (niebieskie)


def _crc16_x25(data: bytes, crc: int = 0xFFFF) -> int:
    for byte in data:
        tmp = byte ^ (crc & 0xFF)
        tmp = (tmp ^ (tmp << 4)) & 0xFF
        crc = ((crc >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4)) & 0xFFFF
    return crc


def _build_mavlink_v2_frame(
    msgid: int, payload: bytes, seq: int = 0, sysid: int = 255, compid: int = 1
) -> bytes:
    """Buduje wychodzaca (do wyslania) ramke MAVLink v2 - odwrotnosc
    _iter_mavlink_frames. Uzywane do komend sterujacych lidarem (np.
    ustawienie trybu pracy), nie tylko do parsowania danych przychodzacych."""
    header = bytes([len(payload), 0, 0, seq & 0xFF, sysid, compid]) + bytes(
        [msgid & 0xFF, (msgid >> 8) & 0xFF, (msgid >> 16) & 0xFF]
    )
    crc = _crc16_x25(header + payload)
    crc = _crc16_x25(bytes([CRC_EXTRA.get(msgid, 0)]), crc)
    return bytes([MAGIC]) + header + payload + struct.pack("<H", crc)


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


def _parse_imu_packet(payload: bytes) -> dict:
    unpacked = struct.unpack(IMU_FMT, payload)
    quaternion = unpacked[0:4]           # x, y, z, w
    angular_velocity = unpacked[4:7]     # rad/s, osie x,y,z
    linear_acceleration = unpacked[7:10]  # m/s^2, osie x,y,z
    packet_id = unpacked[10]

    return {
        "packet_id": packet_id,
        "quaternion": quaternion,
        "angular_velocity": angular_velocity,
        "linear_acceleration": linear_acceleration,
    }


def _range_aux_to_cloud(
    aux: dict,
    dist: dict,
    range_min: float = MIN_RANGE_M,
    range_max: float = MAX_RANGE_M,
    intensity_max: int = MAX_INTENSITY,
) -> List[Tuple[float, float, float, int]]:
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

    points: List[Tuple[float, float, float, int]] = []
    for j in range(POINTS_PER_SCAN):
        r = dist["ranges"][j]
        intensity = aux["reflect_data"][j]  # odbicie 0-255, wieksze = silniejszy sygnal odbity
        # r == 0: brak echa. r >= 0xFFFF: sentinel producenta (poza zasiegiem/nasycenie).
        # Odrzucamy tez punkty blizej niz range_min - to szum odbity od obudowy/mocowania lidara,
        # a nie realne przeszkody - oraz punkty o silnym odbiciu (intensity > intensity_max,
        # "niebieskie") - to zazwyczaj podloga/gladkie powierzchnie, a nie realne przeszkody.
        range_float = range_scale * r
        if 0 < r < 0xFFFF and range_min <= range_float <= range_max and intensity <= intensity_max:
            sin_alpha, cos_alpha = math.sin(pitch_cur), math.cos(pitch_cur)
            sin_beta, cos_beta = math.sin(yaw_cur), math.cos(yaw_cur)

            A = (-cos_theta * sin_ksi + sin_theta * sin_alpha * cos_ksi) * range_float + bias_laser_beam
            B = cos_alpha * cos_ksi * range_float

            x = cos_beta * A - sin_beta * B
            y = sin_beta * A + cos_beta * B
            z = (sin_theta * sin_ksi + cos_theta * sin_alpha * cos_ksi) * range_float + z_bias

            points.append((x, y, z, intensity))

        pitch_cur += pitch_step
        yaw_cur += yaw_step

    return points


class UnitreeL1Lidar(LidarInterface):
    """Odczyt Unitree LiDAR L1 po porcie szeregowym (ramki MAVLink)."""

    def __init__(
        self,
        port: str = "/dev/ttyUSB0",
        baud: int = 2_000_000,
        range_min: float = MIN_RANGE_M,
        range_max: float = MAX_RANGE_M,
        intensity_max: int = MAX_INTENSITY,
    ):
        self.port = port
        self.baud = baud
        self.range_min = range_min
        self.range_max = range_max
        self.intensity_max = intensity_max

        self._ser: serial.Serial | None = None
        self._buf = bytearray()
        self._pending_dist: dict = {}
        self._pending_aux: dict = {}
        self._latest_imu: dict | None = None
        self._cmd_seq = 0

    def set_working_mode(self, mode: int) -> None:
        """Wysyla do lidaru komende CONFIG_LIDAR_WORKING_MODE (msgid=14).
        Oficjalny tester C++ zawsze woli setLidarWorkingMode(NORMAL) zaraz
        po initialize() - bez tego lidar moze pozostac w trybie, w jakim
        zostal poprzednio, wlacznie ze STANDBY (silniki/pomiar wylaczone)."""
        if self._ser is None:
            return
        frame = _build_mavlink_v2_frame(
            WORK_MODE_MSGID, struct.pack("<B", mode), seq=self._cmd_seq
        )
        self._cmd_seq = (self._cmd_seq + 1) & 0xFF
        self._ser.write(frame)

    def start(self) -> None:
        if self._ser is not None:
            return
        self._ser = serial.Serial(self.port, self.baud, timeout=0)
        self.set_working_mode(WORK_MODE_NORMAL)

    def stop(self) -> None:
        if self._ser is not None:
            self.set_working_mode(WORK_MODE_STANDBY)
            self._ser.close()
            self._ser = None
        self._buf = bytearray()
        self._pending_dist.clear()
        self._pending_aux.clear()
        self._latest_imu = None

    def read_points(self) -> List[Tuple[float, float, float, int]]:
        if self._ser is None:
            return []

        chunk = self._ser.read(1024 * 64)
        if not chunk:
            return []

        self._buf.extend(chunk)
        frames, self._buf = _iter_mavlink_frames(self._buf)

        points: List[Tuple[float, float, float, int]] = []
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
            elif msgid == 19 and len(payload) == IMU_LEN:
                self._latest_imu = _parse_imu_packet(payload)

            if pid is not None and pid in self._pending_dist and pid in self._pending_aux:
                points.extend(
                    _range_aux_to_cloud(
                        self._pending_aux.pop(pid),
                        self._pending_dist.pop(pid),
                        range_min=self.range_min,
                        range_max=self.range_max,
                        intensity_max=self.intensity_max,
                    )
                )

        return points

    def read_imu(self) -> dict | None:
        """Zwraca ostatnia odebrana ramke IMU (aktualizowana przy okazji
        read_points(), bo dane przychodza tym samym strumieniem szeregowym):
        {"packet_id", "quaternion": (x,y,z,w), "angular_velocity": (x,y,z)
        [rad/s], "linear_acceleration": (x,y,z) [m/s^2]}, albo None, jesli
        jeszcze nie odebrano zadnej ramki IMU."""
        return self._latest_imu
