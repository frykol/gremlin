from .interface import WSClientInterface
from .client import WSClient
from .client_dummy import WSClientDummy
import os


def create_client(is_dev: bool, uri: str, instruction_tab) -> WSClientInterface:
    # If parent process provided pipe FDs, use PipeWSClient to communicate over pipes
    if os.environ.get("USE_PIPE_WS") == "1":
        from .pipe_client import PipeWSClient
        return PipeWSClient(uri, instruction_tab)

    if is_dev:
        return WSClient(uri, instruction_tab)
    else:
        return WSClientDummy(uri, [])
