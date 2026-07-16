#!/usr/bin/env python3
"""
Szybki test sprawdzajacy, czy Unitree LiDAR L1 dziala poprawnie.

Laczy sie z portem szeregowym, przez zadany czas zlicza ramki MAVLink
(DIST=16, AUX=17), sprawdza ich CRC oraz to, czy udaje sie z nich
zlozyc jakiekolwiek prawidlowe punkty. Konczy sie kodem wyjscia 0 (PASS)
albo 1 (FAIL) i drukuje diagnoze.

Skrypt jest samodzielny (nie zalezy od innych plikow w repo).

Uzycie:
    python3 test_lidar_connection.py [--port /dev/ttyUSB0] [--baud 2000000] [--seconds 5]
"""
import sys
import time
import math
import struct
import argparse

try:
    import serial
except ImportError:
    print("FAIL: brak modulu 'pyserial' (pip install pyserial)", file=sys.stderr)
    sys.exit(1)

MAGIC = 0xFD
CRC_EXTRA = {16: 74, 17: 99}
DIST_FMT = "<HHH240s"
DIST_LEN = struct.calcsize(DIST_FMT)
AUX_FMT = "<5I16f2HB120s"
AUX_LEN = struct.calcsize(AUX_FMT)


def crc16_x25(data, crc=0xFFFF):
    for byte in data:
        tmp = byte ^ (crc & 0xFF)
        tmp = (tmp ^ (tmp << 4)) & 0xFF
        crc = ((crc >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4)) & 0xFFFF
    return crc


def iter_mavlink_frames(buf: bytearray):
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
        crc = crc16_x25(crc_span)
        crc = crc16_x25(bytes([CRC_EXTRA.get(msgid, 0)]), crc)
        crc_received = buf[i + 10 + payload_len] | (buf[i + 10 + payload_len + 1] << 8)

        if crc == crc_received:
            payload = bytes(buf[i + 10: i + 10 + payload_len])
            frames.append((msgid, payload))
            i += total_len
        else:
            i += 1

    return frames, buf[i:]


def parse_distance_packet(payload):
    packet_id, packet_cnt, payload_size, point_data = struct.unpack(DIST_FMT, payload)
    ranges = struct.unpack("<120H", point_data)
    return {"packet_id": packet_id, "ranges": ranges}


def parse_auxiliary_packet(payload):
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


def range_aux_to_cloud(aux, dist):
    if aux["packet_id"] != dist["packet_id"]:
        return []

    range_scale = 0.001
    z_bias = 0.0445
    points_num_of_scan = 120
    bias_laser_beam = aux["b_axis_dist"] / 1000

    sin_theta = math.sin(aux["theta_angle"])
    cos_theta = math.cos(aux["theta_angle"])
    sin_ksi = math.sin(aux["ksi_angle"])
    cos_ksi = math.cos(aux["ksi_angle"])

    pitch_cur = aux["sys_vertical_angle_start"] * math.pi / 180.0
    pitch_step = aux["sys_vertical_angle_span"] * math.pi / 180.0
    yaw_cur = aux["com_horizontal_angle_start"] * math.pi / 180.0
    yaw_step = aux["com_horizontal_angle_step"] / points_num_of_scan * math.pi / 180.0

    points = []
    for j in range(points_num_of_scan):
        r = dist["ranges"][j]
        # r == 0: brak echa. r >= 0xFFFF: poza zasiegiem / nasycenie -> odrzucamy,
        # bo L1 ma specyfikowany max range 30 m.
        if 0 < r < 0xFFFF and r * 0.001 <= 30.0:
            range_float = range_scale * r
            sin_alpha, cos_alpha = math.sin(pitch_cur), math.cos(pitch_cur)
            sin_beta, cos_beta = math.sin(yaw_cur), math.cos(yaw_cur)

            A = (-cos_theta * sin_ksi + sin_theta * sin_alpha * cos_ksi) * range_float + bias_laser_beam
            B = cos_alpha * cos_ksi * range_float

            x = cos_beta * A - sin_beta * B
            y = sin_beta * A + cos_beta * B
            z = (sin_theta * sin_ksi + cos_theta * sin_alpha * cos_ksi) * range_float + z_bias
            intensity = aux["reflect_data"][j]
            points.append((x, y, z, intensity))

        pitch_cur += pitch_step
        yaw_cur += yaw_step

    return points


def run_test(port: str, baud: int, seconds: float) -> bool:
    print(f"Otwieram {port} @ {baud} baud, test przez {seconds}s...")
    try:
        ser = serial.Serial(port, baud, timeout=0)
    except serial.SerialException as e:
        print(f"FAIL: nie mozna otworzyc portu {port}: {e}")
        return False

    buf = bytearray()
    pending_dist = {}
    pending_aux = {}
    frame_count = {16: 0, 17: 0}
    points_total = 0
    bytes_total = 0

    t_end = time.time() + seconds
    try:
        while time.time() < t_end:
            chunk = ser.read(1024 * 64)
            if chunk:
                bytes_total += len(chunk)
                buf.extend(chunk)
                frames, buf = iter_mavlink_frames(buf)

                for msgid, payload in frames:
                    pid = None
                    if msgid == 16 and len(payload) == DIST_LEN:
                        d = parse_distance_packet(payload)
                        pending_dist[d["packet_id"]] = d
                        pid = d["packet_id"]
                        frame_count[16] += 1
                    elif msgid == 17 and len(payload) == AUX_LEN:
                        a = parse_auxiliary_packet(payload)
                        pending_aux[a["packet_id"]] = a
                        pid = a["packet_id"]
                        frame_count[17] += 1

                    if pid is not None and pid in pending_dist and pid in pending_aux:
                        points_total += len(
                            range_aux_to_cloud(pending_aux.pop(pid), pending_dist.pop(pid))
                        )
            else:
                time.sleep(0.002)
    finally:
        ser.close()

    print(f"Odebrano bajtow:        {bytes_total}")
    print(f"Ramki DIST (msgid=16):  {frame_count[16]}")
    print(f"Ramki AUX  (msgid=17):  {frame_count[17]}")
    print(f"Punkty odczytane:       {points_total}")

    if bytes_total == 0:
        print("FAIL: brak jakichkolwiek danych z portu - lidar niepodlaczony, zly port albo brak zasilania.")
        return False
    if frame_count[16] == 0 and frame_count[17] == 0:
        print("FAIL: dane przychodza, ale nie udalo sie sparsowac zadnej ramki MAVLink (zle CRC / zly baud rate).")
        return False
    if points_total == 0:
        print("FAIL: ramki DIST/AUX odebrane, ale zero prawidlowych punktow (lidar moze sie nie kręcić / brak echa).")
        return False

    print("PASS: lidar dziala poprawnie.")
    return True


def main():
    ap = argparse.ArgumentParser(description="Test polaczenia z Unitree LiDAR L1")
    ap.add_argument("--port", default="/dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=2_000_000)
    ap.add_argument("--seconds", type=float, default=5.0)
    args = ap.parse_args()

    ok = run_test(args.port, args.baud, args.seconds)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
