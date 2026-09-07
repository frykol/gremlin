"""
CLI entrypoint: spina bridge_manager, udp_listener, frame_parser,
accumulator, recorder/player i ws_server w jedna dzialajaca aplikacje.

Tryb live:    python3 -m backend.app --serial-port /dev/ttyUSB0 --bridge-path <sciezka>
Tryb replay:  python3 -m backend.app --replay nagranie.bin
"""

import argparse
import asyncio
import logging
import time
from typing import Optional

import websockets

from .accumulator import PointAccumulator
from .bridge_manager import BridgeManager
from .frame_parser import FrameParseError, ImuFrame, ScanFrame, parse_udp_datagram
from .player import FramePlayer
from .recorder import FrameRecorder
from .static_files import DEFAULT_FRONTEND_DIR, make_static_process_request
from .udp_listener import create_udp_listener
from .ws_server import (
    LATENCY_NOT_AVAILABLE,
    ClientRegistry,
    encode_imu_frame,
    encode_metrics_frame,
    encode_scan_frame,
)

logger = logging.getLogger("lidar_viewer")

BROADCAST_INTERVAL_S = 0.05  # ~20Hz gorny limit czestotliwosci wysylki chmury
METRICS_INTERVAL_S = 1.0
BRIDGE_MAX_RESTARTS = 3
# Pelny snapshot okna przy realistycznym strumieniu (21.6k pkt/s x 3s) to
# ~65k punktow = ~1MB i ~34ms kodowania NA KAZDY TICK broadcastu, blokujac
# petle asyncio na tyle, ze grozi gubieniem datagramow UDP. Decymacja tnie
# to do stalego budzetu, kosztem gestosci chmury.
DEFAULT_MAX_BROADCAST_POINTS = 20000


def decimate(points: list, max_points: int) -> list:
    """
    Podprobkowanie co N-ty punkt, tak by wynik mial <= max_points elementow.

    Stride-based (a nie "pierwsze N"), zeby zachowac ksztalt calej chmury -
    obciecie do prefiksu pokazaloby tylko fragment okna czasowego.
    """
    total = len(points)
    if max_points <= 0 or total <= max_points:
        return points
    stride = -(-total // max_points)  # ceil, gwarantuje len(wynik) <= max_points
    return points[::stride]


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Standalone Unitree L1 UDP viewer")
    parser.add_argument("--serial-port", default=None, help="Port szeregowy lidaru (tryb live)")
    parser.add_argument("--replay", default=None, help="Plik nagrania do odtworzenia zamiast trybu live")
    parser.add_argument("--record", default=None, help="Sciezka pliku do nagrania surowych ramek live")
    parser.add_argument("--udp-host", default="127.0.0.1")
    parser.add_argument("--udp-port", type=int, default=12345)
    parser.add_argument("--ws-host", default="0.0.0.0")
    parser.add_argument("--ws-port", type=int, default=8080)
    parser.add_argument(
        "--bridge-path",
        default="unilidar_publisher_udp",
        help="Sciezka do binarki bridge'a (unilidar_publisher_udp)",
    )
    parser.add_argument("--window-seconds", type=float, default=3.0)
    parser.add_argument("--max-range-m", type=float, default=8.0)
    parser.add_argument(
        "--frontend-dir",
        default=DEFAULT_FRONTEND_DIR,
        help="Katalog ze statycznym frontendem serwowanym z tego samego portu co WS",
    )
    parser.add_argument(
        "--broadcast-interval",
        type=float,
        default=BROADCAST_INTERVAL_S,
        help="Odstep miedzy broadcastami chmury w sekundach (domyslnie ~20Hz)",
    )
    parser.add_argument(
        "--max-broadcast-points",
        type=int,
        default=DEFAULT_MAX_BROADCAST_POINTS,
        help="Gorny limit punktow w jednej ramce Scan WS; nadmiar jest decymowany",
    )
    args = parser.parse_args(argv)

    if not args.replay and not args.serial_port:
        parser.error("wymagany --serial-port (tryb live) albo --replay <plik>")
    return args


class App:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.accumulator = PointAccumulator(
            window_seconds=args.window_seconds, max_range_m=args.max_range_m
        )
        self.clients = ClientRegistry()
        self.recorder: Optional[FrameRecorder] = FrameRecorder(args.record) if args.record else None
        self.latest_imu: Optional[ImuFrame] = None
        self.replay_mode = bool(args.replay)
        self.broadcast_interval = getattr(args, "broadcast_interval", BROADCAST_INTERVAL_S)
        self.max_broadcast_points = getattr(
            args, "max_broadcast_points", DEFAULT_MAX_BROADCAST_POINTS
        )
        self._scan_count = 0
        self._scan_count_window_start = time.monotonic()
        self._last_broadcast_point_count = 0

    def handle_datagram(self, data: bytes) -> None:
        if self.recorder is not None:
            self.recorder.write(data)
        try:
            frame = parse_udp_datagram(data)
        except FrameParseError as exc:
            logger.debug("odrzucono uszkodzona ramke: %s", exc)
            return

        if isinstance(frame, ScanFrame):
            self.accumulator.add_scan(frame)
            self._scan_count += 1
        elif isinstance(frame, ImuFrame):
            self.latest_imu = frame

    async def broadcast_loop(self) -> None:
        while True:
            await asyncio.sleep(self.broadcast_interval)
            # Czysc okno takze bez naplywu nowych skanow - inaczej po
            # smierci zrodla danych chmura zostaje zamrozona i wyglada
            # jak dzialajaca.
            self.accumulator.prune()
            count = len(self.accumulator)
            if count:
                sampled = decimate(self.accumulator.snapshot(), self.max_broadcast_points)
                points = [(p.x, p.y, p.z, p.intensity) for p in sampled]
                await self.clients.broadcast(encode_scan_frame(points))
            elif self._last_broadcast_point_count:
                # Przejscie "byly punkty -> nie ma punktow": wyslij pusta
                # chmure, zeby frontend pokazal pusty stan, a nie stara
                # chmure w nieskonczonosc.
                await self.clients.broadcast(encode_scan_frame([]))
            self._last_broadcast_point_count = count

            if self.latest_imu is not None:
                await self.clients.broadcast(
                    encode_imu_frame(
                        self.latest_imu.quaternion,
                        self.latest_imu.angular_velocity,
                        self.latest_imu.linear_acceleration,
                    )
                )

    async def metrics_loop(self) -> None:
        while True:
            await asyncio.sleep(METRICS_INTERVAL_S)
            now = time.monotonic()
            elapsed = now - self._scan_count_window_start
            fps = self._scan_count / elapsed if elapsed > 0 else 0.0
            self._scan_count = 0
            self._scan_count_window_start = now

            # W trybie replay `stamp` to znacznik czasu Z NAGRANIA, wiec
            # `now - stamp` liczy WIEK NAGRANIA (obserwowane: ~1.79e12 ms),
            # a nie opoznienie pipeline'u. Zamiast prezentowac bezsensowna
            # liczbe jako pomiar, wysylamy sentinel -> frontend pokazuje N/A.
            latency_ms = LATENCY_NOT_AVAILABLE
            if not self.replay_mode and self.latest_imu is not None:
                # best-effort: zaklada zsynchronizowane zegary hosta i
                # lidaru; jesli nie sa, ta wartosc jest tylko orientacyjna
                latency_ms = max(0.0, (time.time() - self.latest_imu.stamp) * 1000.0)

            await self.clients.broadcast(
                encode_metrics_frame(
                    fps=fps,
                    points_in_window=len(self.accumulator),
                    latency_ms=latency_ms,
                )
            )

    async def replay_loop(self, path: str) -> None:
        player = FramePlayer(path)
        async for data in player.aplay():
            self.handle_datagram(data)

    async def ws_handler(self, websocket) -> None:
        self.clients.add(websocket)
        try:
            await websocket.wait_closed()
        finally:
            self.clients.remove(websocket)


async def _run_live(app: App, args: argparse.Namespace) -> None:
    bridge = BridgeManager(
        executable_path=args.bridge_path,
        serial_port=args.serial_port,
        dest_ip=args.udp_host,
        dest_port=args.udp_port,
    )
    transport = None
    restarts = 0
    try:
        bridge.start()
        transport = await create_udp_listener(args.udp_host, args.udp_port, app.handle_datagram)

        while True:
            await asyncio.sleep(1.0)
            if not bridge.is_alive():
                restarts += 1
                if restarts > BRIDGE_MAX_RESTARTS:
                    logger.error("Bridge padl %d razy - poddaje sie.", restarts)
                    raise SystemExit(1)
                logger.warning("Bridge nie zyje, restart (%d/%d)...", restarts, BRIDGE_MAX_RESTARTS)
                bridge.start()
    finally:
        if transport is not None:
            transport.close()
        bridge.stop()


async def main_async() -> None:
    logging.basicConfig(level=logging.INFO)
    args = parse_args()
    app = App(args)

    # Jeden port: statyczny frontend po HTTP + WS na tym samym gniezdzie
    # (spec: "Serwuje frontend (statyczne pliki) + WS na jednym porcie").
    ws_server = await websockets.serve(
        app.ws_handler,
        args.ws_host,
        args.ws_port,
        process_request=make_static_process_request(args.frontend_dir),
    )
    logger.info(
        "Frontend + WS na http://%s:%d/ (pliki z %s)",
        args.ws_host,
        args.ws_port,
        args.frontend_dir,
    )
    background_tasks = [
        asyncio.create_task(app.broadcast_loop()),
        asyncio.create_task(app.metrics_loop()),
    ]

    try:
        if args.replay:
            await app.replay_loop(args.replay)
        else:
            await _run_live(app, args)
    finally:
        for task in background_tasks:
            task.cancel()
        ws_server.close()
        await ws_server.wait_closed()
        if app.recorder is not None:
            app.recorder.close()


def main() -> None:
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
