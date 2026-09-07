"""
Zamykanie serwera LiDAR przy PODLACZONEJ przegladarce.

Regresja o realnych skutkach operacyjnych: handle_ws wisi w
`async for _msg in ws` dopoki klient sie nie rozlaczy, a aiohttp w
graceful shutdown czeka na zakonczenie handlerow. Z otwarta karta
przegladarki proces po SIGTERM zamykal gniazdo nasluchujace, ale NIGDY sie
nie konczyl - zaobserwowane na zywo: proces zyl 10 minut po SIGTERM, bez
LISTEN na 8767, za to z ESTABLISHED do przegladarki. Stad braly sie
procesy-zombie i powtarzajacy sie EADDRINUSE przy kolejnych uruchomieniach
(w jednym momencie dzialaly 4 rownolegle kopie backendu).
"""

import asyncio
import types

import pytest
from aiohttp import ClientSession, web

from backend.lidar.http_api import build_app


def _args(port: int) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        lidar_bridge_path="/bin/true",
        lidar_serial_port="/dev/null",
        udp_host="127.0.0.1",
        udp_port=12398,
        window_seconds=600.0,
        max_range_m=8.0,
        broadcast_interval=0.05,
        max_broadcast_points=65000,
        record=None,
        replay=None,
    )


@pytest.mark.asyncio
async def test_server_shuts_down_while_a_websocket_client_is_connected():
    port = 18811
    app = build_app(_args(port))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()

    async with ClientSession() as session:
        async with session.ws_connect(f"http://127.0.0.1:{port}/ws/lidar") as ws:
            # Klient jest podlaczony i NIC nie wysyla - dokladnie jak
            # przegladarka z otwarta zakladka Lidar.
            assert not ws.closed
            assert len(app["websockets"]) == 1

            # Zamkniecie serwera nie moze czekac w nieskonczonosc na tego
            # klienta. Bez on_shutdown zamykajacego polaczenia to wisi.
            await asyncio.wait_for(runner.cleanup(), timeout=10.0)

    assert len(app["websockets"]) == 0


@pytest.mark.asyncio
async def test_shutdown_is_clean_with_no_clients():
    port = 18812
    app = build_app(_args(port))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()

    await asyncio.wait_for(runner.cleanup(), timeout=10.0)

    assert len(app["websockets"]) == 0
