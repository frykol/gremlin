from src.websocket_config import build_ws_uri


def test_build_ws_uri_prefers_configured_values():
    config = {
        "websocket": {
            "scheme": "wss",
            "host": "10.0.0.5",
            "port": 9000,
        }
    }

    assert build_ws_uri(config) == "wss://10.0.0.5:9000"


def test_build_ws_uri_falls_back_to_localhost():
    assert build_ws_uri({}) == "ws://127.0.0.1:8765"
