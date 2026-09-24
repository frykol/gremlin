#!/usr/bin/env python3
"""
HTTP + WebSocket serwis dla LiDAR-a na ESP32P4 (protokol UDP LIDR, patrz
esp_rasp_test/PROTOCOL.txt). W odroznieniu od backend/lidar/http_api.py
(Unitree L1) nie ma tu zadnego bridge'a do odpalania - ESP wysyla dane
niezaleznie po Ethernecie, jak tylko jest wlaczony, wiec UDP listener
startuje razem z procesem (bez /api/start).

Wystawia:
  GET /ws/esp_lidar - WebSocket ze strumieniem Scan + IMU. Oba uzywaja
                       DOKLADNIE tego samego binarnego formatu co
                       backend/lidar/ws_server (encode_scan_frame,
                       encode_imu_frame) - format IMU z ESP (quaternion +
                       angular_velocity + linear_acceleration, patrz
                       esp_rasp_test/PROTOCOL.txt) jest celowo identyczny
                       jak Unitree L1, wiec frontend moze uzyc TEGO SAMEGO
                       dekodera co zakladka Lidar
                       (site/public/lidar/js/ws_client.js).

Usage:
  python -m backend.esp_lidar.http_api --port 8769 --udp-port 5005
"""

import argparse
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

from aiohttp import WSCloseCode, web

from backend.lidar.udp_listener import create_udp_listener
from backend.lidar.ws_server import (
    ClientRegistry,
    encode_imu_frame,
    encode_obstacles_frame,
    encode_scan_frame,
)

from .accumulator import PointFrameAccumulator
from .control import ESP_COMMAND_IP, ESP_COMMAND_PORT, EspControlClient
from .frame_parser import (
    FrameParseError,
    ImuPacket,
    ObstaclePacket,
    decode_packet,
)

logger = logging.getLogger("esp_lidar")

BROADCAST_INTERVAL_S = 0.05  # ~20Hz, spojne z backend/lidar
METRICS_INTERVAL_S = 1.0

COMMAND_IDS = {
    "ping": 1,
    "get_status": 2,
    "set_lidar_active": 3,
    "set_stream_mask": 4,
    "set_fusion_active": 5,
    "clear_history": 6,
    "set_cloud_active": 7,
    "set_imu_active": 8,
    "set_obstacles_active": 9,
}
ZERO_ARGUMENT_COMMANDS = {"ping", "get_status", "clear_history"}
BOOLEAN_COMMANDS = {
    "set_lidar_active",
    "set_fusion_active",
    "set_cloud_active",
    "set_imu_active",
    "set_obstacles_active",
}


@dataclass
class EspObstacleCluster:
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float
    centroid_x: float
    centroid_y: float
    centroid_z: float
    point_count: int
    mean_intensity: float = 0.0
    intensity_std: float = 0.0
    anomaly_score: float = 0.5


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ESP32P4 LiDAR HTTP+WS service for gremlin")
    parser.add_argument("--port", type=int, default=8769, help="HTTP+WebSocket port")
    parser.add_argument("--udp-host", default="0.0.0.0")
    parser.add_argument("--udp-port", type=int, default=5005)
    parser.add_argument("--esp-ip", default=ESP_COMMAND_IP)
    parser.add_argument("--control-port", type=int, default=ESP_COMMAND_PORT)
    parser.add_argument("--broadcast-interval", type=float, default=BROADCAST_INTERVAL_S)
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


class EspLidarService:
    def __init__(self, broadcast_interval: float):
        self.accumulator = PointFrameAccumulator()
        self.clients = ClientRegistry()
        self.broadcast_interval = broadcast_interval
        self._packet_count = 0
        self._packet_count_window_start = time.monotonic()
        self._last_broadcast_point_count = 0
        self.latest_imu: Optional[ImuPacket] = None
        self.latest_obstacles: Optional[list[EspObstacleCluster]] = None
        self._obstacle_frame_id: Optional[int] = None
        self._obstacle_packet_count = 0
        self._obstacle_packets = {}
        self._obstacle_version = 0
        self._last_broadcast_obstacle_version = 0

    def handle_datagram(self, data: bytes) -> None:
        try:
            packet = decode_packet(data)
        except FrameParseError as exc:
            logger.debug("odrzucono uszkodzony pakiet ESP LiDAR: %s", exc)
            return
        if packet is None:
            return  # nieznany typ wiadomosci - nic do zrobienia
        if isinstance(packet, ImuPacket):
            self.latest_imu = packet
            return
        if isinstance(packet, ObstaclePacket):
            self._handle_obstacle_packet(packet)
            return
        self.accumulator.add_packet(
            packet.frame_id,
            packet.packet_id,
            packet.packet_count,
            packet.points,
        )
        self._packet_count += 1

    def _handle_obstacle_packet(self, packet: ObstaclePacket) -> None:
        if self._obstacle_frame_id is not None and packet.frame_id < self._obstacle_frame_id:
            return
        if packet.frame_id != self._obstacle_frame_id:
            self._obstacle_frame_id = packet.frame_id
            self._obstacle_packet_count = packet.packet_count
            self._obstacle_packets = {}
        elif packet.packet_count != self._obstacle_packet_count:
            return

        if packet.packet_id in self._obstacle_packets:
            return
        self._obstacle_packets[packet.packet_id] = packet.obstacles
        if len(self._obstacle_packets) != self._obstacle_packet_count:
            return

        records = []
        for packet_id in sorted(self._obstacle_packets):
            for obstacle in self._obstacle_packets[packet_id]:
                records.append(
                    EspObstacleCluster(
                        x_min=obstacle.center_x - obstacle.size_x / 2,
                        x_max=obstacle.center_x + obstacle.size_x / 2,
                        y_min=obstacle.center_y - obstacle.size_y / 2,
                        y_max=obstacle.center_y + obstacle.size_y / 2,
                        z_min=obstacle.center_z - obstacle.size_z / 2,
                        z_max=obstacle.center_z + obstacle.size_z / 2,
                        centroid_x=obstacle.center_x,
                        centroid_y=obstacle.center_y,
                        centroid_z=obstacle.center_z,
                        point_count=obstacle.point_count,
                    )
                )
        self.latest_obstacles = records
        self._obstacle_version += 1

    async def broadcast_loop(self) -> None:
        while True:
            await asyncio.sleep(self.broadcast_interval)
            count = len(self.accumulator)
            if count:
                await self.clients.broadcast(encode_scan_frame(self.accumulator.snapshot()))
            elif self._last_broadcast_point_count:
                await self.clients.broadcast(encode_scan_frame([]))
            self._last_broadcast_point_count = count

            if self.latest_obstacles is not None and (
                self._obstacle_version != self._last_broadcast_obstacle_version
            ):
                await self.clients.broadcast(encode_obstacles_frame(self.latest_obstacles))
                self._last_broadcast_obstacle_version = self._obstacle_version

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
            elapsed = now - self._packet_count_window_start
            packet_rate = self._packet_count / elapsed if elapsed > 0 else 0.0
            self._packet_count = 0
            self._packet_count_window_start = now
            await self.clients.broadcast(
                encode_metrics_frame(packet_rate, len(self.accumulator))
            )


def encode_metrics_frame(packet_rate: float, points_in_buffer: int) -> str:
    import json

    # Klucze zgodne z backend/lidar/ws_server.encode_metrics_frame, zeby
    # frontend mogl uzyc tego samego dekodera (site/public/lidar/js/ws_client.js)
    # bez pisania osobnego parsera JSON.
    return json.dumps(
        {"type": "metrics", "fps": packet_rate, "points_in_window": points_in_buffer, "latency_ms": -1.0}
    )


async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    service: EspLidarService = request.app["service"]
    adapter = WsAdapter(ws)
    service.clients.add(adapter)
    request.app["websockets"].add(ws)
    try:
        async for _msg in ws:
            pass  # klient nic nie wysyla, strumien jest jednokierunkowy
    except asyncio.CancelledError:
        pass
    finally:
        service.clients.remove(adapter)
        request.app["websockets"].discard(ws)
    return ws


def _validate_command(body: object) -> tuple[int, list[int]]:
    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object")
    command = body.get("command")
    args = body.get("args", [])
    if command not in COMMAND_IDS:
        raise ValueError(f"Unknown command: {command}")
    if not isinstance(args, list) or any(isinstance(value, bool) or not isinstance(value, int) for value in args):
        raise ValueError("args must be a list of integers")
    if command in ZERO_ARGUMENT_COMMANDS and args:
        raise ValueError(f"{command} does not accept arguments")
    if command in BOOLEAN_COMMANDS and (len(args) != 1 or args[0] not in (0, 1)):
        raise ValueError(f"{command} expects one argument: 0 or 1")
    if command == "set_stream_mask" and (len(args) != 1 or not 0 <= args[0] <= 7):
        raise ValueError("set_stream_mask expects one argument from 0 to 7")
    if len(args) > 4:
        raise ValueError("at most four arguments are allowed")
    return COMMAND_IDS[command], args


async def _send_control(request: web.Request, command_id: int, args: list[int]) -> web.Response:
    client: EspControlClient = request.app["control_client"]
    try:
        ack = await asyncio.to_thread(client.send, command_id, args)
    except (TimeoutError, OSError) as exc:
        return web.json_response({"error": str(exc)}, status=502)
    return web.json_response(ack)


async def handle_control_command(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        command_id, args = _validate_command(body)
    except (ValueError, TypeError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return await _send_control(request, command_id, args)


async def handle_control_status(request: web.Request) -> web.Response:
    return await _send_control(request, COMMAND_IDS["get_status"], [])


async def on_shutdown(app: web.Application) -> None:
    for ws in set(app["websockets"]):
        await ws.close(code=WSCloseCode.GOING_AWAY, message=b"server shutdown")
    app["websockets"].clear()


async def on_cleanup(app: web.Application) -> None:
    transport = app.get("udp_transport")
    if transport is not None:
        transport.close()
    for task in app["background_tasks"]:
        task.cancel()
    await app["service"].clients.close()


def create_app(args: argparse.Namespace) -> web.Application:
    app = web.Application(middlewares=[cors_middleware])
    app["service"] = EspLidarService(args.broadcast_interval)
    app["control_client"] = EspControlClient(
        getattr(args, "esp_ip", ESP_COMMAND_IP),
        getattr(args, "control_port", ESP_COMMAND_PORT),
    )
    app["websockets"] = set()
    app.router.add_get("/ws/esp_lidar", handle_ws)
    app.router.add_post("/api/esp_lidar/command", handle_control_command)
    app.router.add_get("/api/esp_lidar/status", handle_control_status)
    app.on_shutdown.append(on_shutdown)
    app.on_cleanup.append(on_cleanup)

    async def start_background(app: web.Application) -> None:
        service: EspLidarService = app["service"]
        app["udp_transport"] = await create_udp_listener(
            args.udp_host, args.udp_port, service.handle_datagram
        )
        app["background_tasks"] = [
            asyncio.create_task(service.broadcast_loop()),
            asyncio.create_task(service.metrics_loop()),
        ]
        logger.info(
            "ESP LiDAR UDP listener na %s:%d, WS na /ws/esp_lidar (port %d)",
            args.udp_host, args.udp_port, args.port,
        )

    app.on_startup.append(start_background)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    args = parse_args()
    app = create_app(args)
    web.run_app(app, port=args.port)


if __name__ == "__main__":
    main()
