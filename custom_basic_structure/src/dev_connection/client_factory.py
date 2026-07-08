from .interface import WSClientInterface
from .client import WSClient
from .client_dummy import WSClientDummy

def create_client(is_dev: bool, uri: str, instruction_tab) -> WSClientInterface:
    if is_dev:
        return WSClient(uri, instruction_tab)
    else:
        return WSClientDummy(uri, [])
