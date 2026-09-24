import struct

from backend.esp_lidar.http_api import EspLidarService


def make_obstacle_datagram(
    frame_id, packet_id, packet_count, total_obstacles, obstacles
):
    header = struct.pack(
        "<4sBBHIHHHHQI",
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
    return header + b"".join(struct.pack("<7fHH", *item) for item in obstacles)


def obstacle(center_x):
    return (center_x, 2.0, 0.5, 0.4, 0.6, 1.2, 1.1, 12, 3)


def test_obstacle_packets_wait_for_complete_frame():
    service = EspLidarService(broadcast_interval=0.01)

    service.handle_datagram(make_obstacle_datagram(7, 0, 2, 2, [obstacle(1.0)]))
    assert service.latest_obstacles is None

    service.handle_datagram(make_obstacle_datagram(7, 1, 2, 2, [obstacle(2.0)]))

    assert [item.centroid_x for item in service.latest_obstacles] == [1.0, 2.0]


def test_empty_obstacle_frame_clears_latest_obstacles():
    service = EspLidarService(broadcast_interval=0.01)
    service.latest_obstacles = [obstacle(1.0)]

    service.handle_datagram(make_obstacle_datagram(8, 0, 1, 0, []))

    assert service.latest_obstacles == []