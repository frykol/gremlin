from src.websocket_config import build_bind_address


def test_build_bind_address_uses_configured_values():
    config = {
        "ws_server": {
            "bind_host": "10.0.0.5",
            "port": 9000,
        }
    }

    assert build_bind_address(config) == ("10.0.0.5", 9000)


def test_build_bind_address_defaults_to_all_interfaces():
    assert build_bind_address({}) == ("0.0.0.0", 8765)


def test_build_bind_address_defaults_port_when_only_host_given():
    config = {"ws_server": {"bind_host": "192.168.1.50"}}

    assert build_bind_address(config) == ("192.168.1.50", 8765)
