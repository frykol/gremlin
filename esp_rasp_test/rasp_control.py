#!/usr/bin/env python3

import argparse
import random
import socket
import struct
import sys
import time

ESP_IP = "192.168.50.10"
ESP_COMMAND_PORT = 5006
TIMEOUT_S = 1.0
RETRIES = 3

MAGIC = b"LIDR"
VERSION = 1
HEADER_SIZE = 32
MSG_COMMAND = 128
MSG_COMMAND_ACK = 129

HEADER = struct.Struct("<4sBBHIHHHHQI")
COMMAND_PAYLOAD = struct.Struct("<IIII")
ACK_PAYLOAD = struct.Struct("<IIII")

CMD_PING = 1
CMD_GET_STATUS = 2
CMD_SET_LIDAR_ACTIVE = 3
CMD_SET_STREAM_MASK = 4
CMD_SET_FUSION_ACTIVE = 5
CMD_CLEAR_HISTORY = 6
CMD_SET_CLOUD_ACTIVE = 7
CMD_SET_IMU_ACTIVE = 8
CMD_SET_OBSTACLES_ACTIVE = 9

RESULT_NAMES = {
    0: "OK",
    1: "BAD_COMMAND",
    2: "BAD_ARGUMENT",
    3: "UNSUPPORTED",
    4: "INTERNAL_ERROR",
}

STREAM_CLOUD = 0x01
STREAM_IMU = 0x02
STREAM_OBSTACLES = 0x04
STREAM_ALL = STREAM_CLOUD | STREAM_IMU | STREAM_OBSTACLES


def bool_value(text):
    value = text.lower()
    if value in ("1", "on", "true", "yes", "enable", "enabled"):
        return 1
    if value in ("0", "off", "false", "no", "disable", "disabled"):
        return 0
    raise argparse.ArgumentTypeError("expected on/off")


def make_request_id():
    # Enough to pair an ACK with one CLI invocation. Random low bits also make
    # two rapidly started processes unlikely to collide.
    return ((time.monotonic_ns() >> 10) ^ random.getrandbits(32)) & 0xFFFFFFFF


def encode_command(request_id, command_id, args):
    args = list(args) + [0, 0, 0, 0]
    args = args[:4]
    header = HEADER.pack(
        MAGIC,
        VERSION,
        MSG_COMMAND,
        HEADER_SIZE,
        request_id,
        command_id,
        0,
        COMMAND_PAYLOAD.size,
        0,
        0,
        0,
    )
    return header + COMMAND_PAYLOAD.pack(*args)


def decode_ack(data, expected_request_id):
    if len(data) != HEADER_SIZE + ACK_PAYLOAD.size:
        return None

    (
        magic,
        version,
        message_type,
        header_size,
        request_id,
        command_id,
        result,
        payload_size,
        _field18,
        timestamp_us,
        _reserved,
    ) = HEADER.unpack_from(data, 0)

    if (
        magic != MAGIC
        or version != VERSION
        or message_type != MSG_COMMAND_ACK
        or header_size != HEADER_SIZE
        or request_id != expected_request_id
        or payload_size != ACK_PAYLOAD.size
    ):
        return None

    state_flags, stream_mask, command_count, uptime_ms = ACK_PAYLOAD.unpack_from(
        data, HEADER_SIZE
    )

    return {
        "request_id": request_id,
        "command_id": command_id,
        "result": result,
        "timestamp_us": timestamp_us,
        "lidar_active": bool(state_flags & 0x01),
        "fusion_enabled": bool(state_flags & 0x02),
        "stream_mask": stream_mask,
        "command_count": command_count,
        "uptime_ms": uptime_ms,
    }


def send_command(command_id, *args):
    request_id = make_request_id()
    packet = encode_command(request_id, command_id, args)

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(TIMEOUT_S)

        for attempt in range(1, RETRIES + 1):
            sock.sendto(packet, (ESP_IP, ESP_COMMAND_PORT))
            deadline = time.monotonic() + TIMEOUT_S

            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                sock.settimeout(remaining)

                try:
                    data, addr = sock.recvfrom(256)
                except socket.timeout:
                    break

                if addr[0] != ESP_IP:
                    continue

                ack = decode_ack(data, request_id)
                if ack is not None:
                    return ack

            if attempt < RETRIES:
                print(f"no ACK, retry {attempt + 1}/{RETRIES}...", file=sys.stderr)

    raise TimeoutError(f"ESP {ESP_IP}:{ESP_COMMAND_PORT} did not answer")


def print_status(ack):
    result_name = RESULT_NAMES.get(ack["result"], str(ack["result"]))
    enabled = []
    if ack["stream_mask"] & STREAM_CLOUD:
        enabled.append("cloud")
    if ack["stream_mask"] & STREAM_IMU:
        enabled.append("imu")
    if ack["stream_mask"] & STREAM_OBSTACLES:
        enabled.append("obstacles")

    print(
        f"ACK {result_name}: "
        f"lidar={'ON' if ack['lidar_active'] else 'OFF'} "
        f"fusion={'ON' if ack['fusion_enabled'] else 'OFF'} "
        f"streams={','.join(enabled) if enabled else 'none'} "
        f"commands={ack['command_count']} "
        f"uptime={ack['uptime_ms'] / 1000.0:.1f}s"
    )


def parse_stream_mask(text):
    value = text.strip().lower()
    if value in ("all", "on"):
        return STREAM_ALL
    if value in ("none", "off"):
        return 0

    mask = 0
    for item in value.split(","):
        item = item.strip()
        if item == "cloud":
            mask |= STREAM_CLOUD
        elif item == "imu":
            mask |= STREAM_IMU
        elif item in ("obstacle", "obstacles"):
            mask |= STREAM_OBSTACLES
        elif item:
            raise argparse.ArgumentTypeError(f"unknown stream: {item}")
    return mask


def main():
    parser = argparse.ArgumentParser(
        description="Send control commands from Raspberry Pi to ESP32-P4 LiDAR bridge"
    )
    sub = parser.add_subparsers(dest="action", required=True)

    sub.add_parser("ping")
    sub.add_parser("status")
    sub.add_parser("clear-history")

    p = sub.add_parser("lidar", help="logical LiDAR pipeline on/off")
    p.add_argument("state", type=bool_value)

    p = sub.add_parser("fusion")
    p.add_argument("state", type=bool_value)

    p = sub.add_parser("cloud")
    p.add_argument("state", type=bool_value)

    p = sub.add_parser("imu")
    p.add_argument("state", type=bool_value)

    p = sub.add_parser("obstacles")
    p.add_argument("state", type=bool_value)

    p = sub.add_parser("streams")
    p.add_argument("mask", type=parse_stream_mask,
                   help="all, none, or comma list: cloud,imu,obstacles")

    args = parser.parse_args()

    if args.action == "ping":
        ack = send_command(CMD_PING)
    elif args.action == "status":
        ack = send_command(CMD_GET_STATUS)
    elif args.action == "clear-history":
        ack = send_command(CMD_CLEAR_HISTORY)
    elif args.action == "lidar":
        ack = send_command(CMD_SET_LIDAR_ACTIVE, args.state)
    elif args.action == "fusion":
        ack = send_command(CMD_SET_FUSION_ACTIVE, args.state)
    elif args.action == "cloud":
        ack = send_command(CMD_SET_CLOUD_ACTIVE, args.state)
    elif args.action == "imu":
        ack = send_command(CMD_SET_IMU_ACTIVE, args.state)
    elif args.action == "obstacles":
        ack = send_command(CMD_SET_OBSTACLES_ACTIVE, args.state)
    elif args.action == "streams":
        ack = send_command(CMD_SET_STREAM_MASK, args.mask)
    else:
        raise AssertionError(args.action)

    print_status(ack)
    if ack["result"] != 0:
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except TimeoutError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
