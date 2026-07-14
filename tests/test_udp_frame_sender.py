from unittest.mock import MagicMock

from src.dev_connection.udp_frame_sender import UdpFrameSender


def test_set_target_updates_destination_used_by_send_frame():
    sender = UdpFrameSender(host="192.168.1.162", port=8766)
    sender._socket = MagicMock()

    sender.set_target("10.0.0.9", 9000)
    sender.send_frame(frame_id=1, timestamp=1.0, payload=b"x")

    sent_addr = sender._socket.sendto.call_args[0][1]
    assert sent_addr == ("10.0.0.9", 9000)


def test_set_target_before_any_send_is_used_immediately():
    sender = UdpFrameSender(host="old-host", port=1)
    sender._socket = MagicMock()

    sender.set_target("new-host", 2)

    assert sender.host == "new-host"
    assert sender.port == 2
