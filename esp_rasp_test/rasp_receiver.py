#!/usr/bin/env python3

import socket
import struct
import time

UDP_IP = "0.0.0.0"
UDP_PORT = 5005
FRAME_TIMEOUT_S = 0.25

HEADER = struct.Struct("<4sBBHIHHHHQI")
POINT = struct.Struct("<fffBBH")

MAGIC = b"LIDR"
VERSION = 1
MSG_POINT_CLOUD = 1
MSG_IMU = 2  # reserved; ESP does not send IMU yet
HEADER_SIZE = 32


def on_point_cloud(frame_id, timestamp_us, points):
    """
    points: list[(x, y, z, intensity)]

    Replace this body with your 3D renderer / point-cloud pipeline.
    """
    print(
        f"frame={frame_id} points={len(points)} "
        f"timestamp_us={timestamp_us}"
    )


def decode_packet(data):
    if len(data) < HEADER_SIZE:
        return None

    (
        magic,
        version,
        message_type,
        header_size,
        frame_id,
        packet_id,
        packet_count,
        point_count,
        total_point_count,
        timestamp_us,
        _reserved,
    ) = HEADER.unpack_from(data, 0)

    if magic != MAGIC:
        return None
    if version != VERSION:
        return None
    if message_type != MSG_POINT_CLOUD:
        return None
    if header_size != HEADER_SIZE:
        return None
    if packet_count == 0 or packet_id >= packet_count:
        return None

    expected_size = HEADER_SIZE + point_count * POINT.size
    if len(data) != expected_size:
        return None

    points = []
    offset = HEADER_SIZE

    for _ in range(point_count):
        x, y, z, intensity, _flags, _reserved = POINT.unpack_from(data, offset)
        points.append((x, y, z, intensity))
        offset += POINT.size

    return {
        "frame_id": frame_id,
        "packet_id": packet_id,
        "packet_count": packet_count,
        "total_point_count": total_point_count,
        "timestamp_us": timestamp_us,
        "points": points,
    }


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))

    frames = {}

    print(f"Listening for LiDAR UDP on {UDP_IP}:{UDP_PORT}")

    while True:
        data, _addr = sock.recvfrom(2048)
        packet = decode_packet(data)

        if packet is None:
            continue

        now = time.monotonic()
        frame_id = packet["frame_id"]

        frame = frames.get(frame_id)
        if frame is None:
            frame = {
                "timestamp_us": packet["timestamp_us"],
                "packet_count": packet["packet_count"],
                "total_point_count": packet["total_point_count"],
                "packets": {},
                "last_update": now,
            }
            frames[frame_id] = frame

        # Reject inconsistent packets carrying the same frame_id.
        if (
            frame["packet_count"] != packet["packet_count"]
            or frame["total_point_count"] != packet["total_point_count"]
        ):
            del frames[frame_id]
            continue

        frame["packets"][packet["packet_id"]] = packet["points"]
        frame["last_update"] = now

        if len(frame["packets"]) == frame["packet_count"]:
            points = []

            for packet_id in range(frame["packet_count"]):
                chunk = frame["packets"].get(packet_id)
                if chunk is None:
                    break
                points.extend(chunk)
            else:
                if len(points) == frame["total_point_count"]:
                    on_point_cloud(frame_id, frame["timestamp_us"], points)

            del frames[frame_id]

        # UDP has no retransmission. Old incomplete frames are simply dropped.
        stale = [
            fid
            for fid, partial in frames.items()
            if now - partial["last_update"] > FRAME_TIMEOUT_S
        ]
        for fid in stale:
            del frames[fid]


if __name__ == "__main__":
    main()
