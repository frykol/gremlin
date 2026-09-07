#!/usr/bin/env python3
"""
HTTP + WebSocket API dla LiDAR service integrowanego z gremlin.

Wystawia na jednym porcie:
  POST /api/lidar/start  - startuje bridge (unilidar_publisher_udp) + UDP listener
  POST /api/lidar/stop   - zatrzymuje bridge + UDP listener
  GET  /ws/lidar         - WebSocket ze strumieniem Scan/IMU/metrics

Frontend (site/public/tabs/lidar.js) najpierw woła /api/lidar/start, potem
łączy się z /ws/lidar - stąd oba muszą działać razem na tym samym porcie.

Usage:
  python -m backend.lidar.http_api \
    --lidar-bridge-path /path/to/unilidar_publisher_udp \
    --lidar-serial-port /dev/ttyUSB0 \
    --port 8767
"""

import argparse
import asyncio
import logging
from typing import Optional

from aiohttp import WSCloseCode, web

from .app import App, BROADCAST_INTERVAL_S, DEFAULT_MAX_BROADCAST_POINTS
from .bridge_manager import BridgeManager
from .udp_listener import create_udp_listener

logger = logging.getLogger("lidar_http_api")

BRIDGE_MAX_RESTARTS = 3


class WsAdapter:
    """Adaptuje aiohttp.web.WebSocketResponse do interfejsu .send() uzywanego
    przez ClientRegistry (napisanego pod biblioteke `websockets`)."""

    def __init__(self, ws: web.WebSocketResponse):
        self._ws = ws

    async def send(self, message) -> None:
        if isinstance(message, (bytes, bytearray)):
            await self._ws.send_bytes(message)
        else:
            await self._ws.send_str(message)


class LidarRuntime:
    """Zarzadza cyklem zycia bridge'a + UDP listenera, sterowanym przez
    /api/lidar/start i /api/lidar/stop (a nie startowanym eagerly przy
    starcie procesu - frontend decyduje kiedy lidar ma zaczac dzialac)."""

    def __init__(self, app: App, bridge_path: str, serial_port: str, udp_host: str, udp_port: int):
        self.app = app
        self.bridge_path = bridge_path
        self.serial_port = serial_port
        self.udp_host = udp_host
        self.udp_port = udp_port
        self.bridge: Optional[BridgeManager] = None
        self.transport = None
        self._watchdog_task: Optional[asyncio.Task] = None

    @property
    def running(self) -> bool:
        return self.bridge is not None and self.bridge.is_alive()

    async def start(self) -> None:
        if self.running:
            return
        self.bridge = BridgeManager(
            executable_path=self.bridge_path,
            serial_port=self.serial_port,
            dest_ip=self.udp_host,
            dest_port=self.udp_port,
        )
        self.bridge.start()
        self.transport = await create_udp_listener(self.udp_host, self.udp_port, self.app.handle_datagram)
        self._watchdog_task = asyncio.create_task(self._watchdog())
        logger.info("LiDAR runtime wystartowal")

    async def stop(self) -> None:
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
            self._watchdog_task = None
        if self.transport is not None:
            self.transport.close()
            self.transport = None
        if self.bridge is not None:
            # bridge.stop() jest synchroniczne i blokuje az do 10s (patrz
            # komentarz w bridge_manager.py - graceful shutdown do STANDBY
            # potrzebuje na to realnego czasu). Bez to_thread ten call
            # blokowalby CALY event loop (broadcast_loop, obstacle_loop,
            # wszystkich podlaczonych klientow WS) na caly ten czas.
            await asyncio.to_thread(self.bridge.stop)
            self.bridge = None
        logger.info("LiDAR runtime zatrzymany")

    async def _watchdog(self) -> None:
        restarts = 0
        while True:
            await asyncio.sleep(1.0)
            if self.bridge is not None and not self.bridge.is_alive():
                restarts += 1
                if restarts > BRIDGE_MAX_RESTARTS:
                    logger.error("Bridge padl %d razy - poddaje sie.", restarts)
                    return
                logger.warning("Bridge nie zyje, restart (%d/%d)...", restarts, BRIDGE_MAX_RESTARTS)
                self.bridge.start()


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LiDAR HTTP+WS service for gremlin")
    parser.add_argument("--lidar-bridge-path", required=True, help="Path to unilidar_publisher_udp")
    parser.add_argument("--lidar-serial-port", required=True, help="Serial port (e.g. /dev/ttyUSB0)")
    parser.add_argument("--port", type=int, default=8767, help="HTTP+WebSocket port")
    parser.add_argument("--udp-host", default="127.0.0.1")
    parser.add_argument("--udp-port", type=int, default=12345)
    # Duza wartosc CELOWO - accumulator ma teraz max_points (ring buffer,
    # patrz accumulator.py) jako GLOWNY mechanizm retencji ("punkty zostaja
    # az zostana nadpisane"). To pole to juz tylko bezpiecznik na martwe
    # zrodlo (bridge padl/koniec nagrania) - przy realnym tempie strumienia
    # ponizej capacity krotki window_seconds (dawne 3.0) kasowal punkty z
    # wieku ZANIM ring buffer sie zapelnil, capujac chmure duzo ponizej
    # max-broadcast-points (obserwowane: ~27k zamiast 65k przy ~9k pkt/s).
    parser.add_argument("--window-seconds", type=float, default=600.0)
    parser.add_argument("--max-range-m", type=float, default=8.0)
    parser.add_argument("--broadcast-interval", type=float, default=BROADCAST_INTERVAL_S)
    parser.add_argument("--max-broadcast-points", type=int, default=DEFAULT_MAX_BROADCAST_POINTS)

    # Pola wymagane przez App.__init__, ale nieistotne dla http_api
    parser.add_argument("--record", default=None)
    parser.add_argument("--replay", default=None)

    return parser.parse_args(argv)


@web.middleware
async def cors_middleware(request: web.Request, handler):
    if request.method == "OPTIONS":
        resp = web.Response()
    else:
        resp = await handler(request)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "*"
    return resp


async def handle_start(request: web.Request) -> web.Response:
    runtime: LidarRuntime = request.app["runtime"]
    try:
        await runtime.start()
    except Exception as exc:
        logger.exception("Nie udalo sie wystartowac LiDAR runtime")
        return web.json_response({"status": "error", "detail": str(exc)}, status=500)
    return web.json_response({"status": "started"})


async def handle_stop(request: web.Request) -> web.Response:
    runtime: LidarRuntime = request.app["runtime"]
    await runtime.stop()
    return web.json_response({"status": "stopped"})


async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    app: App = request.app["lidar_app"]
    adapter = WsAdapter(ws)
    app.clients.add(adapter)
    # Rejestr surowych polaczen - potrzebny, zeby on_cleanup mogl je
    # ZAMKNAC przy wylaczaniu serwera (patrz on_cleanup).
    request.app["websockets"].add(ws)
    try:
        async for _msg in ws:
            pass  # klient nic nie wysyla - strumien jest jednokierunkowy
    except asyncio.CancelledError:
        # Zamkniecie serwera (Ctrl+C -> aiohttp GracefulExit) anuluje ten
        # dlugo-trwajacy handler w trakcie oczekiwania na wiadomosc. Bez
        # tego zlapania wyjatek propaguje sie niezlapany, a aiohttp 3.14.3
        # ma wewnetrzny quirk (InvalidStateError przy _handler_waiter.
        # set_result na juz-anulowanym future) dajacy brzydki traceback w
        # logach przy KAZDYM graceful shutdown. Zwracamy normalnie zamiast
        # pozwalac wyjatkowi eskalowac - to legalny wzorzec dla handlera
        # HTTP/WS podczas zamykania serwera (nie "connienie" anulowania
        # ogolnie, tylko obsluga zamkniecia TEGO polaczenia).
        pass
    finally:
        app.clients.remove(adapter)
        request.app["websockets"].discard(ws)
    return ws


async def on_shutdown(app: web.Application) -> None:
    """
    Zamyka WSZYSTKIE otwarte polaczenia WebSocket.

    KONIECZNE, nie kosmetyczne: handle_ws wisi w `async for _msg in ws`
    dopoki klient sie nie rozlaczy, a aiohttp w graceful shutdown czeka na
    zakonczenie handlerow. Z otwarta karta przegladarki proces po SIGTERM
    zamykal gniazdo nasluchujace, ale NIGDY sie nie konczyl - zaobserwowane
    na zywo: proces zyl 10 minut po SIGTERM, bez LISTEN na 8767, za to z
    ESTABLISHED do przegladarki. Stad braly sie procesy-zombie i
    powtarzajacy sie EADDRINUSE przy kolejnych uruchomieniach.

    Musi byc w on_shutdown (przed on_cleanup), bo to faza, w ktorej aiohttp
    domyka polaczenia - patrz dokumentacja aiohttp "Graceful shutdown".
    """
    for ws in set(app["websockets"]):
        await ws.close(code=WSCloseCode.GOING_AWAY, message=b"server shutdown")
    app["websockets"].clear()


async def on_cleanup(app: web.Application) -> None:
    runtime: LidarRuntime = app["runtime"]
    await runtime.stop()
    for task in app["background_tasks"]:
        task.cancel()
    # Kazdy klient WS ma wlasne zadanie-pisarza (patrz ClientRegistry) -
    # bez tego zostalyby wiszace zadania przy zamykaniu.
    await app["lidar_app"].clients.close()


def build_app(args: argparse.Namespace) -> web.Application:
    lidar_app = App(args)
    runtime = LidarRuntime(
        lidar_app,
        bridge_path=args.lidar_bridge_path,
        serial_port=args.lidar_serial_port,
        udp_host=args.udp_host,
        udp_port=args.udp_port,
    )

    app = web.Application(middlewares=[cors_middleware])
    app["lidar_app"] = lidar_app
    app["websockets"] = set()
    app["runtime"] = runtime
    app.router.add_post("/api/lidar/start", handle_start)
    app.router.add_post("/api/lidar/stop", handle_stop)
    app.router.add_route("OPTIONS", "/api/lidar/start", handle_start)
    app.router.add_route("OPTIONS", "/api/lidar/stop", handle_stop)
    app.router.add_get("/ws/lidar", handle_ws)

    async def start_background_tasks(app: web.Application) -> None:
        app["background_tasks"] = [
            asyncio.create_task(lidar_app.broadcast_loop()),
            asyncio.create_task(lidar_app.metrics_loop()),
            asyncio.create_task(lidar_app.obstacle_loop()),
        ]

    app.on_startup.append(start_background_tasks)
    app.on_shutdown.append(on_shutdown)
    app.on_cleanup.append(on_cleanup)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    args = parse_args()
    app = build_app(args)
    logger.info(f"LiDAR HTTP+WS API na http://0.0.0.0:{args.port}/ (start: POST /api/lidar/start, ws: /ws/lidar)")
    web.run_app(app, host="0.0.0.0", port=args.port, print=None)


if __name__ == "__main__":
    main()
