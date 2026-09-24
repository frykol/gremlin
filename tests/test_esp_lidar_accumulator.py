from backend.esp_lidar.accumulator import PointFrameAccumulator


def test_snapshot_changes_only_after_complete_frame_and_replaces_previous_frame():
    accumulator = PointFrameAccumulator()

    accumulator.add_packet(12, 1, 2, [(1.0, 0.0, 0.0, 10)])
    assert accumulator.snapshot() == []

    accumulator.add_packet(12, 0, 2, [(0.0, 0.0, 0.0, 20)])
    assert accumulator.snapshot() == [
        (0.0, 0.0, 0.0, 20.0),
        (1.0, 0.0, 0.0, 10.0),
    ]

    accumulator.add_packet(13, 0, 1, [(9.0, 0.0, 0.0, 30)])
    assert accumulator.snapshot() == [(9.0, 0.0, 0.0, 30.0)]


def test_incomplete_frame_is_discarded_when_next_frame_starts():
    accumulator = PointFrameAccumulator()

    accumulator.add_packet(20, 0, 2, [(1.0, 0.0, 0.0, 10)])
    accumulator.add_packet(21, 0, 1, [(2.0, 0.0, 0.0, 20)])

    assert accumulator.snapshot() == [(2.0, 0.0, 0.0, 20.0)]


def test_late_packet_from_older_frame_does_not_replace_current_frame():
    accumulator = PointFrameAccumulator()

    accumulator.add_packet(30, 0, 1, [(3.0, 0.0, 0.0, 30)])
    accumulator.add_packet(29, 0, 1, [(2.0, 0.0, 0.0, 20)])

    assert accumulator.snapshot() == [(3.0, 0.0, 0.0, 30.0)]
