import struct
import pytest

from backend.esp_lidar.http_api import EspLidarService
from backend.esp_lidar.udp_forwarder import (
    HEADER_FORMAT,
    HEADER_SIZE,
    MAGIC,
    MSG_POINT_CLOUD,
    VERSION,
    PointCloudUdpForwarder,
    encode_scan_datagrams,
)


def unpack_datagram(datagram):
    header = struct.unpack(HEADER_FORMAT, datagram[:HEADER_SIZE])
    return header, datagram[HEADER_SIZE:]


def test_scan_datagram_preserves_websocket_point_payload():
    points = [(1.0, 2.0, 3.0, 4.0), (-1.0, 0.5, 2.5, 255.0)]

    datagrams = encode_scan_datagrams(17, points)

    assert len(datagrams) == 1
    header, payload = unpack_datagram(datagrams[0])
    assert header == (MAGIC, VERSION, MSG_POINT_CLOUD, HEADER_SIZE, 17, 0, 1, 2)
    assert struct.unpack("<8f", payload) == tuple(value for point in points for value in point)


def test_scan_datagrams_split_points_and_keep_fragment_order_metadata():
    points = [(float(index), 0.0, 0.0, 10.0) for index in range(5)]

    datagrams = encode_scan_datagrams(23, points, max_datagram_size=52)

    assert len(datagrams) == 3
    decoded = [unpack_datagram(datagram) for datagram in datagrams]
    assert [item[0][5:8] for item in decoded] == [(0, 3, 5), (1, 3, 5), (2, 3, 5)]
    assert [len(item[1]) for item in decoded] == [32, 32, 16]
    joined_points = b"".join(item[1] for item in decoded)
    assert struct.unpack("<20f", joined_points) == tuple(
        value for point in points for value in point
    )


def test_empty_scan_emits_one_header_only_datagram():
    datagrams = encode_scan_datagrams(24, [])

    assert len(datagrams) == 1
    header, payload = unpack_datagram(datagrams[0])
    assert header == (MAGIC, VERSION, MSG_POINT_CLOUD, HEADER_SIZE, 24, 0, 1, 0)
    assert payload == b""


def test_scan_datagram_size_must_fit_header_and_one_point():
    with pytest.raises(ValueError, match="at least"):
        encode_scan_datagrams(1, [(0.0, 0.0, 0.0, 0.0)], max_datagram_size=HEADER_SIZE + 15)


def test_forwarder_rejects_invalid_datagram_size_during_initialization():
    with pytest.raises(ValueError, match="at least"):
        PointCloudUdpForwarder("192.0.2.10", 5010, max_datagram_size=HEADER_SIZE + 15)


def test_forwarder_sends_each_fragment_to_configured_destination():
    sent = []

    class FakeSocket:
        def sendto(self, datagram, destination):
            sent.append((datagram, destination))

        def close(self):
            pass

    forwarder = PointCloudUdpForwarder(
        "192.0.2.10", 5010, max_datagram_size=52, socket_factory=lambda *_: FakeSocket()
    )
    try:
        forwarder.send_frame(8, [(float(index), 0.0, 0.0, 1.0) for index in range(3)])
    finally:
        forwarder.close()

    assert len(sent) == 2
    assert {destination for _, destination in sent} == {("192.0.2.10", 5010)}


def test_service_forwards_completed_scan_snapshot():
    forwarded = []

    class FakeForwarder:
        def send_frame(self, frame_id, points):
            forwarded.append((frame_id, points))

    service = EspLidarService(0.001, udp_forwarder=FakeForwarder())
    point_packet = struct.pack(
        "<4sBBHIHHHHQI", b"LIDR", 1, 1, 32, 42, 0, 1, 1, 1, 123, 0
    ) + struct.pack("<fffBBH", 1.0, 2.0, 3.0, 4, 0, 0)
    service.handle_datagram(point_packet)

    assert forwarded == [(42, [(1.0, 2.0, 3.0, 4.0)])]
    assert service.accumulator.completed_frame_version == 1


def test_service_forwards_first_empty_completed_frame():
    forwarded = []

    class FakeForwarder:
        def send_frame(self, frame_id, points):
            forwarded.append((frame_id, points))

    service = EspLidarService(0.001, udp_forwarder=FakeForwarder())
    empty_packet = struct.pack(
        "<4sBBHIHHHHQI", b"LIDR", 1, 1, 32, 43, 0, 1, 0, 0, 123, 0
    )
    service.handle_datagram(empty_packet)

    assert forwarded == [(43, [])]


def test_service_forwards_each_frame_even_when_multiple_complete_quickly():
    forwarded = []

    class FakeForwarder:
        def send_frame(self, frame_id, points):
            forwarded.append((frame_id, points))

    service = EspLidarService(0.001, udp_forwarder=FakeForwarder())
    for frame_id, x in ((44, 1.0), (45, 2.0), (46, 3.0)):
        packet = struct.pack(
            "<4sBBHIHHHHQI", b"LIDR", 1, 1, 32, frame_id, 0, 1, 1, 1, 123, 0
        ) + struct.pack("<fffBBH", x, 0.0, 0.0, 4, 0, 0)
        service.handle_datagram(packet)

    assert [frame_id for frame_id, _ in forwarded] == [44, 45, 46]