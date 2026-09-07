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

import numpy as np
import websockets

from src.hardware.lidar.obstacle_reducer import LidarObstacleReducer

from .accumulator import PointAccumulator
from .anomaly_scorer import ClusterAnomalyScorer
from .bridge_manager import BridgeManager
from .cluster_persistence import ClusterPersistenceTracker
from .frame_parser import FrameParseError, ImuFrame, ScanFrame, parse_udp_datagram
from .obstacle_clustering import cluster_obstacles
from .player import FramePlayer
from .recorder import FrameRecorder
from .static_files import DEFAULT_FRONTEND_DIR, make_static_process_request
from .udp_listener import create_udp_listener
from .ws_server import (
    LATENCY_NOT_AVAILABLE,
    ClientRegistry,
    encode_imu_frame,
    encode_metrics_frame,
    encode_obstacles_frame,
    encode_scan_frame,
)

logger = logging.getLogger("lidar_viewer")

BROADCAST_INTERVAL_S = 0.05  # ~20Hz gorny limit czestotliwosci wysylki chmury
METRICS_INTERVAL_S = 1.0
BRIDGE_MAX_RESTARTS = 3
# Pelny snapshot okna przy realistycznym strumieniu (21.6k pkt/s x 3s) to
# ~65k punktow = ~1MB i ~34ms kodowania NA KAZDY TICK broadcastu (budzet
# tick'a to 50ms przy BROADCAST_INTERVAL_S=0.05s) - blisko granicy, ale
# mieszczace sie, bez gubienia datagramow UDP w testach. Limit dobrany tak,
# by pokrywac cale okno 1:1 (zamiast decymowac/przeprobkowywac je na nowo
# co tick) - inaczej konkretne punkty "migaja"/znikaja miedzy klatkami mimo
# ze wciaz sa w oknie czasowym, bo kazdy tick losuje inne probkowanie.
DEFAULT_MAX_BROADCAST_POINTS = 65000

# Detekcja przeszkod dziala w OSOBNEJ, wolniejszej petli niz surowy
# broadcast (20Hz) - reduce()+cluster_obstacles() na 5000 punktach to
# dodatkowe kilka ms, ktore przy kazdym 20Hz ticku (budzet 50ms, juz
# bliski granicy przy pelnym oknie 65k) grozilyby gubieniem datagramow UDP.
# 5Hz jest wystarczajaco plynne dla wizualizacji obiektow (nie potrzeba
# 20Hz jak surowa chmura punktow).
OBSTACLE_INTERVAL_S = 0.2
# Ile najnowszych punktow z ring buffera akumulatora (do 65k) wchodzi do
# redukcji/klastrowania. Wiekszosc surowych punktow to podloga/stol, ktore
# ground removal i tak odrzuca (na realnych danych: ~91% przy N=5000) -
# male N marnowalo wiec budzet max_output_points reducera (1500) na
# przypadkowo malo obstacle-punktow. Zmierzone empirycznie: N=30000 to
# pierwszy punkt, w ktorym reduce() NIEZAWODNIE wypelnia caly budzet 1500
# (wiecej juz nic nie daje, bo output i tak jest capowany), przy ~13ms
# sredniego czasu - wygodny margines w budzecie 200ms (OBSTACLE_INTERVAL_S).
DEFAULT_OBSTACLE_INPUT_POINTS = 30000
# Jak czesto probowac ponownie skalibrowac plaszczyzne podlogi/stolu -
# adaptuje sie, jesli robota przestawiono na inna wysokosc, bez potrzeby
# restartu procesu. RANSAC to tylko kilka ms, wiec czestotliwosc moze byc
# spora bez obciazania budzetu obstacle_loop.
GROUND_RECALIBRATION_INTERVAL_S = 30.0
# Odstep miedzy PONOWNYMI probami, gdy kalibracja sie NIE udaje (np. robot
# stoi przodem do sciany i fit_ground_plane slusznie odrzuca niepozioma
# plaszczyzne - patrz ground_plane.py). Bez tego backoffu proba leciala by
# w kazdym ticku: zmierzone 41ms RANSAC na 30k punktach to ~20% budzetu
# obstacle_loop (200ms) palone w kolko. 2s to ~2% budzetu, a wciaz szybka
# reakcja, gdy podloga wroci w pole widzenia.
GROUND_RECALIBRATION_RETRY_INTERVAL_S = 2.0
# Jak czesto (re)dopasowywac ClusterAnomalyScorer do zebranej historii
# klastrow (patrz anomaly_scorer.py) - podobny wzorzec jak rekalibracja
# podlogi, zeby model "co jest typowe w tej scenie" nadazal za zmianami
# otoczenia (robot przejechal do innego pokoju itp.).
ANOMALY_SCORER_REFIT_INTERVAL_S = 60.0
# Ile ostatnich obserwacji klastrow trzymac jako historie treningowa -
# limit pamieci/czasu fit(), nie musi rosnac w nieskonczonosc.
ANOMALY_HISTORY_MAX_LEN = 2000


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


def should_recalibrate_ground(
    is_calibrated: bool,
    now: float,
    last_attempt_time: float,
    interval_s: float,
    retry_interval_s: float,
) -> bool:
    """
    Decyzja "czy probowac (re)kalibrowac plaszczyzne podlogi/stolu teraz".

    last_attempt_time to czas ostatniej PROBY (nie ostatniego sukcesu) -
    inaczej trwale nieudana kalibracja ponawialaby RANSAC w kazdym ticku.
    Odstep zalezy od tego, czy mamy juz uzywalna kalibracje:
    - brak kalibracji -> retry_interval_s (krotki, chcemy sie skalibrowac
      jak najszybciej, gdy tylko podloga wroci w pole widzenia),
    - jest kalibracja -> interval_s (dlugi; to tylko odswiezenie na wypadek
      przestawienia robota na inna wysokosc).

    Wydzielone jako czysta funkcja (bez zaleznosci od App/asyncio), zeby
    dalo sie ja przetestowac bez konstruowania calego App.
    """
    threshold = interval_s if is_calibrated else retry_interval_s
    return (now - last_attempt_time) >= threshold


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
    # Patrz identyczny komentarz w http_api.py parse_args - duza wartosc
    # celowo, ring buffer (max_points) jest teraz glownym mechanizmem
    # retencji, to pole to juz tylko bezpiecznik na martwe zrodlo.
    parser.add_argument("--window-seconds", type=float, default=600.0)
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
        self.max_broadcast_points = getattr(
            args, "max_broadcast_points", DEFAULT_MAX_BROADCAST_POINTS
        )
        self.accumulator = PointAccumulator(
            window_seconds=args.window_seconds,
            max_range_m=args.max_range_m,
            # Pojemnosc akumulatora dopasowana do max_broadcast_points -
            # accumulator sam jest ring bufferem (patrz accumulator.py),
            # wiec punkty NIE znikaja przedwczesnie z powodu window_seconds
            # zanim bufor sie zapelni; decimate() w broadcast_loop() staje
            # sie wtedy no-opem w normalnej pracy (snapshot <= limit).
            max_points=self.max_broadcast_points,
        )
        self.clients = ClientRegistry()
        self.recorder: Optional[FrameRecorder] = FrameRecorder(args.record) if args.record else None
        self.latest_imu: Optional[ImuFrame] = None
        self.replay_mode = bool(args.replay)
        self.broadcast_interval = getattr(args, "broadcast_interval", BROADCAST_INTERVAL_S)
        self.obstacle_interval = getattr(args, "obstacle_interval", OBSTACLE_INTERVAL_S)
        self.obstacle_input_points = getattr(
            args, "obstacle_input_points", DEFAULT_OBSTACLE_INPUT_POINTS
        )
        self.obstacle_reducer = LidarObstacleReducer()
        self._scan_count = 0
        self._scan_count_window_start = time.monotonic()
        self._last_broadcast_point_count = 0
        self._last_obstacle_cluster_count = 0
        # -inf, zeby pierwszy tick obstacle_loop() zawsze probowal
        # skalibrowac (warunek "uplynelo >= interval" jest prawdziwy od razu).
        # To czas ostatniej PROBY (udanej lub nie) - patrz
        # should_recalibrate_ground i GROUND_RECALIBRATION_RETRY_INTERVAL_S.
        self._last_ground_calibration_attempt_time = float("-inf")

        self.anomaly_scorer = ClusterAnomalyScorer()
        self._anomaly_history: list = []
        self._last_anomaly_refit_time = float("-inf")

        # Klastry raz wykryte "trzymaja sie" przez chwile (patrz
        # cluster_persistence.py), zeby nie znikaly natychmiast po
        # pojedynczym ticku bez potwierdzenia.
        self.cluster_persistence = ClusterPersistenceTracker()

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

    async def obstacle_loop(self) -> None:
        """
        Redukcja (ground removal + wokselizacja) i klastrowanie w OBIEKTY
        (nie surowe punkty) na ostatnich `obstacle_input_points` z ring
        buffera akumulatora - osobna, wolniejsza petla niz broadcast_loop
        (patrz OBSTACLE_INTERVAL_S).
        """
        while True:
            await asyncio.sleep(self.obstacle_interval)
            recent = self.accumulator.snapshot()[-self.obstacle_input_points :]
            if not recent:
                if self._last_obstacle_cluster_count:
                    await self.clients.broadcast(encode_obstacles_frame([]))
                    self._last_obstacle_cluster_count = 0
                    # Martwe zrodlo danych - trzymane klastry NIE powinny
                    # "wroci" po wznowieniu strumienia, gdyby scena zdazyla
                    # sie zmienic w miedzyczasie (patrz cluster_persistence.py).
                    self.cluster_persistence.reset()
                continue

            # LidarObstacleReducer.reduce() wymaga kolumny intensity - uzywa
            # jej do odrzucenia slabych/zaszumionych odbic (patrz
            # min_intensity w obstacle_reducer.py).
            raw = np.array([(p.x, p.y, p.z, p.intensity) for p in recent], dtype=np.float32)

            # Kalibracja plaszczyzny podlogi/stolu - pierwsza proba jak
            # tylko jest wystarczajaco duzo punktow (RANSAC potrzebuje
            # solidnej proby - patrz ground_plane.py), potem OKRESOWO co
            # GROUND_RECALIBRATION_INTERVAL_S. Bez okresowej rekalibracji
            # przestawienie robota na inna wysokosc (np. z podlogi na stol)
            # zostawialoby STARA, juz nieprawdziwa plaszczyzne na zawsze, az
            # do restartu procesu. Nieudana proba (za malo/za rzadkie
            # punkty) nie blokuje kolejnych - sprobuje ponownie w nastepnym
            # cyklu, zachowujac poprzednia (wciaz uzywalna) kalibracje.
            now = time.monotonic()
            should_calibrate = should_recalibrate_ground(
                self.obstacle_reducer.is_calibrated,
                now,
                self._last_ground_calibration_attempt_time,
                GROUND_RECALIBRATION_INTERVAL_S,
                GROUND_RECALIBRATION_RETRY_INTERVAL_S,
            )
            if should_calibrate and raw.shape[0] >= 300:
                # Czas PROBY zapisujemy zawsze - takze przy porazce - zeby
                # backoff dzialal (patrz GROUND_RECALIBRATION_RETRY_INTERVAL_S).
                self._last_ground_calibration_attempt_time = now
                if self.obstacle_reducer.calibrate_ground(raw):
                    logger.info("Skalibrowano plaszczyzne podlogi/stolu z danych LiDAR")
                else:
                    logger.debug(
                        "Nie znaleziono poziomej plaszczyzny podlogi - "
                        "zostaje poprzednia/domyslna kalibracja"
                    )

            reduced = self.obstacle_reducer.reduce(raw)
            # "Surowy" wynik tego ticku (bez pamieci o przeszlosci) - na
            # tym operuje historia treningowa i scoring, PRZED warstwa
            # trwalosci (persistence dolej dodaje/utrzymuje stare wpisy,
            # ktore nie sa nowa obserwacja tego ticku).
            fresh_clusters = cluster_obstacles(reduced)

            # Historia do treningu scorera - kazdy widziany (fresh) klaster
            # to jedna probka "co jest typowe w tej scenie" (patrz
            # anomaly_scorer.py). Przycinana do ANOMALY_HISTORY_MAX_LEN,
            # zeby nie rosla bez konca.
            self._anomaly_history.extend(fresh_clusters)
            if len(self._anomaly_history) > ANOMALY_HISTORY_MAX_LEN:
                self._anomaly_history = self._anomaly_history[-ANOMALY_HISTORY_MAX_LEN:]

            should_refit = (now - self._last_anomaly_refit_time) >= ANOMALY_SCORER_REFIT_INTERVAL_S
            if should_refit:
                # Zmierzone: fit() na n_estimators=100 to ~320ms na RPi5 -
                # duzo ponad budzet 200ms/tick. build_fitted_model() NIE
                # dotyka self._model (buduje nowy, osobny obiekt), wiec
                # bezpiecznie odpalamy go w watku w tle (asyncio.to_thread)
                # - to oddaje kontrole do event loop na czas treningu,
                # zamiast blokowac CALY proces (w tym broadcast_loop z
                # surowa chmura punktow) na 320ms. Kopia historii (list()),
                # zeby watek w tle nie czytal listy, ktora glowny watek
                # rownolegle modyfikuje (self._anomaly_history.extend()).
                new_model = await asyncio.to_thread(
                    self.anomaly_scorer.build_fitted_model, list(self._anomaly_history)
                )
                if new_model is not None:
                    self.anomaly_scorer.apply_fitted_model(new_model)
                    self._last_anomaly_refit_time = now
                    logger.info(
                        "Przetrenowano ClusterAnomalyScorer (historia: %d klastrow)",
                        len(self._anomaly_history),
                    )

            if fresh_clusters and self.anomaly_scorer.is_fitted:
                scores = self.anomaly_scorer.score(fresh_clusters)
                for cluster, score in zip(fresh_clusters, scores):
                    cluster.anomaly_score = score

            # Warstwa trwalosci: raz wykryty klaster "trzyma sie" przez
            # chwile, nawet jesli TEN konkretny tick go nie potwierdzil
            # (patrz cluster_persistence.py) - to na tym wyniku (nie na
            # fresh_clusters) operuje reszta pipeline'u (wizualizacja).
            clusters = self.cluster_persistence.update(fresh_clusters, now)

            await self.clients.broadcast(encode_obstacles_frame(clusters))
            self._last_obstacle_cluster_count = len(clusters)

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
        asyncio.create_task(app.obstacle_loop()),
    ]

    try:
        if args.replay:
            await app.replay_loop(args.replay)
        else:
            await _run_live(app, args)
    finally:
        for task in background_tasks:
            task.cancel()
        # Kazdy klient WS ma wlasne zadanie-pisarza (patrz ClientRegistry).
        await app.clients.close()
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
