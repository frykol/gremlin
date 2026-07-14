import os

from src.main import _clear_log_file


def test_clear_log_file_truncates_and_reopens_for_append(tmp_path):
    log_path = tmp_path / "sim.log"
    log_path.write_text("old content\nmore old content\n", encoding="utf-8")

    handle = open(log_path, "a", encoding="utf-8")
    try:
        new_handle = _clear_log_file(handle, str(log_path))
        try:
            assert log_path.read_text(encoding="utf-8") == ""

            new_handle.write("fresh line\n")
            new_handle.flush()
            assert log_path.read_text(encoding="utf-8") == "fresh line\n"
        finally:
            new_handle.close()
    finally:
        if not handle.closed:
            handle.close()


def test_clear_log_file_handles_missing_file(tmp_path):
    log_path = tmp_path / "does_not_exist_yet.log"
    handle = open(log_path, "a", encoding="utf-8")

    new_handle = _clear_log_file(handle, str(log_path))
    try:
        assert os.path.exists(log_path)
        assert log_path.read_text(encoding="utf-8") == ""
    finally:
        new_handle.close()
