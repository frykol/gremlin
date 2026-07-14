def build_bind_address(config: dict) -> tuple[str, int]:
    ws_config = config.get("ws_server", {})
    host = ws_config.get("bind_host", "0.0.0.0")
    port = ws_config.get("port", 8765)
    return host, port
