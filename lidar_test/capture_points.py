#!/usr/bin/env python3
"""
Zbiera punkty z Unitree LiDAR L1 i wypisuje/zapisuje je jako
tablice w tablicy [[x, y, z], [x, y, z], ...].

Uzycie:
    python3 capture_points.py [--port /dev/ttyUSB0] [--baud 2000000]
                               [--min-points 1000] [--out points.json]
"""
import sys
import time
import math
import json
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
        if 0 < r < 0xFFFF and r * 0.001 <= 30.0:
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


def capture(port: str, baud: int, min_points: int, timeout_s: float):
    ser = serial.Serial(port, baud, timeout=0)
    print(f"Otwarty {port} @ {baud}, zbieram co najmniej {min_points} punktow...", file=sys.stderr)

    buf = bytearray()
    pending_dist = {}
    pending_aux = {}
    points = []

    t_end = time.time() + timeout_s
    try:
        while len(points) < min_points and time.time() < t_end:
            chunk = ser.read(1024 * 64)
            if chunk:
                buf.extend(chunk)
                frames, buf = iter_mavlink_frames(buf)
                for msgid, payload in frames:
                    pid = None
                    if msgid == 16 and len(payload) == DIST_LEN:
                        d = parse_distance_packet(payload)
                        pending_dist[d["packet_id"]] = d
                        pid = d["packet_id"]
                    elif msgid == 17 and len(payload) == AUX_LEN:
                        a = parse_auxiliary_packet(payload)
                        pending_aux[a["packet_id"]] = a
                        pid = a["packet_id"]

                    if pid is not None and pid in pending_dist and pid in pending_aux:
                        points.extend(range_aux_to_cloud(pending_aux.pop(pid), pending_dist.pop(pid)))
            else:
                time.sleep(0.002)
    finally:
        ser.close()

    return points


def main():
    ap = argparse.ArgumentParser(description="Zbiera punkty [x,y,z] z Unitree LiDAR L1")
    ap.add_argument("--port", default="/dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=2_000_000)
    ap.add_argument("--min-points", type=int, default=1000)
    ap.add_argument("--timeout", type=float, default=30.0, help="max czas zbierania [s]")
    ap.add_argument("--out", default=None, help="jesli podane, zapisuje JSON do pliku zamiast stdout")
    args = ap.parse_args()

    points = capture(args.port, args.baud, args.min_points, args.timeout)
    print(f"Zebrano {len(points)} punktow.", file=sys.stderr)

    array = [[round(x, 4), round(y, 4), round(z, 4)] for x, y, z in points]

    if args.out:
        with open(args.out, "w") as f:
            json.dump(array, f)
        print(f"Zapisano do {args.out}", file=sys.stderr)
    else:
        print(json.dumps(array))


if __name__ == "__main__":
    main()
