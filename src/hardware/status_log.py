STATUS_LOG_PATH = "current_simulation_status.log"


def clear_status_log(path: str = STATUS_LOG_PATH) -> None:
    try:
        open(path, "w", encoding="utf-8").close()
    except OSError as e:
        print(f"Failed to clear status log file: {e}")


def log_device_status(device: str, status: str, path: str = STATUS_LOG_PATH) -> None:
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{device} {status}\n")
    except OSError as e:
        print(f"Failed to write status log file: {e}")
