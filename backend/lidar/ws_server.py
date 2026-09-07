"""
Kodowanie ramek binarnych/JSON wysylanych do przegladarki przez WS oraz
rejestr podlaczonych klientow z broadcastem.

WAZNE: wszystkie naglowki maja rozmiar bedacy wielokrotnoscia 4 bajtow, bo
JS Float32Array rzuca RangeError, jesli byteOffset nie jest wielokrotnoscia
4 - stad uint32 (nie uint8) na pole "type".
"""

import asyncio
import json
import logging
import struct
from typing import TYPE_CHECKING, Iterable, Tuple, Union

if TYPE_CHECKING:
    from .obstacle_clustering import ObstacleCluster

logger = logging.getLogger("lidar_viewer")

SCAN_WS_TYPE = 1
IMU_WS_TYPE = 2
OBSTACLES_WS_TYPE = 3

# Sentinel w ramce metryk: "opoznienia nie da sie sensownie zmierzyc"
# (tryb replay - stamp pochodzi z nagrania, albo brak jeszcze ramki IMU).
# Frontend renderuje wtedy "N/A" zamiast liczby udajacej pomiar.
LATENCY_NOT_AVAILABLE = -1.0

_SCAN_HEADER_FMT = "<II"  # type, pointCount
_IMU_FMT = "<I10f"  # type + quat(4) + angvel(3) + linacc(3)
_OBSTACLES_HEADER_FMT = "<II"  # type, clusterCount
# Wszystkie pola jako float (rowniez point_count) - spojne z reszta
# protokolu (Float32Array po stronie JS), male liczby punktow sa
# reprezentowane w float32 bez utraty precyzji.
_OBSTACLE_RECORD_FMT = "<12f"  # x_min,x_max,y_min,y_max,z_min,z_max,cx,cy,cz,point_count,mean_intensity,anomaly_score


def encode_scan_frame(points: Iterable[Tuple[float, float, float, float]]) -> bytes:
    points = list(points)
    header = struct.pack(_SCAN_HEADER_FMT, SCAN_WS_TYPE, len(points))
    if not points:
        return header
    flat = [v for point in points for v in point]
    body = struct.pack(f"<{len(flat)}f", *flat)
    return header + body


def encode_imu_frame(
    quaternion: Tuple[float, float, float, float],
    angular_velocity: Tuple[float, float, float],
    linear_acceleration: Tuple[float, float, float],
) -> bytes:
    return struct.pack(
        _IMU_FMT,
        IMU_WS_TYPE,
        *quaternion,
        *angular_velocity,
        *linear_acceleration,
    )


def encode_obstacles_frame(clusters: "Iterable[ObstacleCluster]") -> bytes:
    clusters = list(clusters)
    header = struct.pack(_OBSTACLES_HEADER_FMT, OBSTACLES_WS_TYPE, len(clusters))
    if not clusters:
        return header
    body = b"".join(
        struct.pack(
            _OBSTACLE_RECORD_FMT,
            c.x_min,
            c.x_max,
            c.y_min,
            c.y_max,
            c.z_min,
            c.z_max,
            c.centroid_x,
            c.centroid_y,
            c.centroid_z,
            float(c.point_count),
            c.mean_intensity,
            c.anomaly_score,
        )
        for c in clusters
    )
    return header + body


def encode_metrics_frame(fps: float, points_in_window: int, latency_ms: float) -> str:
    return json.dumps(
        {
            "type": "metrics",
            "fps": fps,
            "points_in_window": points_in_window,
            "latency_ms": latency_ms,
        }
    )


# Ile ramek moze czekac w kolejce jednego klienta, zanim zaczniemy
# odrzucac NAJSTARSZE. Male, bo to strumien live - klient, ktory zostal w
# tyle o wiecej niz kilka ramek, i tak ogladalby nieaktualna chmure, a
# nieograniczona kolejka to wyciek pamieci przy 1MB/ramke. Kilka slotow
# wystarcza, zeby wygladzic normalny jitter sieci i zeby ramki roznych
# typow (scan/imu/obstacles/metrics) wysylane pod rzad nie wypychaly sie
# nawzajem.
CLIENT_QUEUE_MAX_FRAMES = 8


class ClientRegistry:
    """
    Rejestr klientow WS z broadcastem nieblokujacym.

    Kazdy klient ma wlasna, OGRANICZONA kolejke i wlasne zadanie-pisarza.
    broadcast() tylko wklada ramke do kolejek i wraca natychmiast - nigdy
    nie czeka na siec.

    Powod: poprzednia wersja robila `await ws.send()` w petli po klientach,
    czyli head-of-line blocking. Zmierzone: jeden wolny klient (slabe wifi,
    pelny bufor TCP) scinal caly pipeline z 20Hz do 2Hz dla WSZYSTKICH -
    lacznie z lokalna przegladarka i petla detekcji przeszkod.

    Gdy kolejka klienta jest pelna, odrzucana jest NAJSTARSZA ramka. To
    poprawne dla strumienia live (lepiej pokazac aktualna chmure niz
    nadrabiac zaleglosci) i ogranicza pamiec przy ~1MB/ramke. Kolejnosc
    ramek u danego klienta jest zachowana, a odrzucanie nie faworyzuje
    zadnego typu ramki.
    """

    def __init__(self, queue_max_frames: int = CLIENT_QUEUE_MAX_FRAMES):
        self.queue_max_frames = queue_max_frames
        # ws -> (queue, writer_task)
        self._channels = {}
        self.dropped_frames = 0

    @property
    def client_count(self) -> int:
        return len(self._channels)

    def add(self, ws) -> None:
        """Musi byc wywolane z dzialajacej petli zdarzen (tworzy zadanie
        pisarza) - wszystkie miejsca uzycia to handlery WS."""
        if ws in self._channels:
            return
        queue: asyncio.Queue = asyncio.Queue(maxsize=self.queue_max_frames)
        task = asyncio.create_task(self._writer(ws, queue))
        self._channels[ws] = (queue, task)

    def remove(self, ws) -> None:
        channel = self._channels.pop(ws, None)
        if channel is None:
            return
        _queue, task = channel
        if not task.done():
            task.cancel()

    async def _writer(self, ws, queue: "asyncio.Queue") -> None:
        """Jedno zadanie na klienta: pobiera ramki z jego kolejki i wysyla
        po kolei. Blokowanie sie TUTAJ dotyka tylko tego jednego klienta."""
        while True:
            message = await queue.get()
            try:
                await ws.send(message)
            except asyncio.CancelledError:
                queue.task_done()
                raise
            except Exception as exc:
                # Celowo szeroko: to zadanie dziala w tle, wiec KAZDY
                # wyciekajacy wyjatek (nie tylko ConnectionClosed) cicho
                # ubilby wysylke do tego klienta. Zamiast tego usuwamy go
                # jawnie - reszta pipeline'u dziala dalej.
                logger.warning("Blad wysylki do klienta WS, usuwam go: %r", exc)
                self._channels.pop(ws, None)
                # Oznacz WSZYSTKIE zalegle pozycje jako obsluzone, zeby
                # drain() czekajacy na join() nie zawisl na martwym kanale.
                queue.task_done()
                while not queue.empty():
                    queue.get_nowait()
                    queue.task_done()
                return
            queue.task_done()

    async def broadcast(self, message: Union[bytes, str]) -> None:
        for ws, (queue, _task) in list(self._channels.items()):
            if queue.full():
                # Zwolnij miejsce, odrzucajac NAJSTARSZA (juz nieaktualna)
                # ramke - klient dostanie swiezsza zamiast nadrabiac zaleglosci.
                try:
                    queue.get_nowait()
                    queue.task_done()  # inaczej join() w drain() nigdy nie wroci
                    self.dropped_frames += 1
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # Wyscig z pisarzem - ramke po prostu pomijamy.
                self.dropped_frames += 1

    async def drain(self) -> None:
        """Czeka, az wszystkie zakolejkowane ramki zostana faktycznie
        wyslane (join() wraca dopiero po task_done() nastepujacym PO
        zakonczeniu send(), wiec obejmuje tez wysylke w locie).

        Do uzytku w testach i przy zamykaniu serwera - normalna praca
        (broadcast_loop) celowo NIE czeka, bo o to wlasnie chodzi w tej
        klasie."""
        queues = [queue for queue, _task in self._channels.values()]
        if queues:
            await asyncio.gather(*(q.join() for q in queues))

    async def close(self) -> None:
        """Zatrzymuje wszystkich pisarzy - do wywolania przy zamykaniu
        serwera, zeby nie zostawiac wiszacych zadan."""
        channels = list(self._channels.values())
        self._channels.clear()
        for _queue, task in channels:
            if not task.done():
                task.cancel()
        if channels:
            await asyncio.gather(*(t for _q, t in channels), return_exceptions=True)
