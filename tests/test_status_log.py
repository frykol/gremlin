import os

from src.hardware.status_log import clear_status_log, log_device_status


def test_clear_status_log_creates_empty_file(tmp_path):
    path = str(tmp_path / "status.log")
    with open(path, "w") as f:
        f.write("stale content\n")

    clear_status_log(path)

    with open(path) as f:
        assert f.read() == ""


def test_clear_status_log_creates_missing_file(tmp_path):
    path = str(tmp_path / "nested" / "status.log")
    os.makedirs(os.path.dirname(path))

    clear_status_log(path)

    assert os.path.exists(path)


def test_log_device_status_appends_line(tmp_path):
    path = str(tmp_path / "status.log")
    clear_status_log(path)

    log_device_status("OAK-D", "SUCCESS", path)
    log_device_status("LIDAR", "ERROR - FALLBACK TO DUMMY", path)

    with open(path) as f:
        lines = f.read().splitlines()

    assert lines == ["OAK-D SUCCESS", "LIDAR ERROR - FALLBACK TO DUMMY"]
