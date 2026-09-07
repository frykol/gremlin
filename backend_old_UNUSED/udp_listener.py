"""Prosty nasluch UDP oparty o asyncio.DatagramProtocol."""

import asyncio
from typing import Callable


class _UdpListenerProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_datagram: Callable[[bytes], None]):
        self._on_datagram = on_datagram

    def datagram_received(self, data: bytes, addr) -> None:
        self._on_datagram(data)


async def create_udp_listener(
    host: str, port: int, on_datagram: Callable[[bytes], None]
) -> asyncio.DatagramTransport:
    loop = asyncio.get_running_loop()
    transport, _protocol = await loop.create_datagram_endpoint(
        lambda: _UdpListenerProtocol(on_datagram),
        local_addr=(host, port),
    )
    return transport
