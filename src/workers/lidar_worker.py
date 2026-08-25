import asyncio
from typing import List, Tuple

from src.hardware.lidar.interface import LidarInterface
from src.robot_state import RobotState, LidarPointBuffer, LidarBufferOverwriteMode


def decimate_points(
    points: List[Tuple[float, float, float, int]], target_count: int
) -> List[Tuple[float, float, float, int]]:
    """Przerzedza liste punktow do co najwyzej target_count, biorac punkty co staly stride."""
    if target_count <= 0 or len(points) <= target_count:
        return points

    stride = len(points) / target_count
    return [points[min(len(points) - 1, int(i * stride))] for i in range(target_count)]


class CycleDecimator:
    """Strumieniowa, ciagla decymacja: kazdy cykl skanowania (cycle_points
    punktow) jest redukowany do ~target_count - bez wyjatkow, wiec bufor
    nigdy nie akumuluje pelnych, nieprzerzedzonych cykli. Kazda partia z
    read_points() jest redukowana i zwracana natychmiast - keep/drop liczone
    jest na biezaco (Bresenham-like akumulator), wiec efekt jest widoczny od
    razu, bez czekania na zebranie calego cyklu."""

    def __init__(self, cycle_points: int, target_count: int):
        self.cycle_points = max(1, cycle_points)
        self.target_count = max(0, target_count)
        self._phase_seen = 0
        self._keep_acc = 0.0

    def process(self, points: List[Tuple[float, float, float, int]]) -> List[Tuple[float, float, float, int]]:
        if self.target_count <= 0 or self.target_count >= self.cycle_points:
            return points

        keep_ratio = self.target_count / self.cycle_points
        out: List[Tuple[float, float, float, int]] = []

        for point in points:
            self._keep_acc += keep_ratio
            if self._keep_acc >= 1.0:
                self._keep_acc -= 1.0
                out.append(point)

            self._phase_seen += 1
            if self._phase_seen >= self.cycle_points:
                self._phase_seen = 0

        return out


class LidarWorker:
    def __init__(self, lidar: LidarInterface, state: RobotState, config: dict, poll_interval: float = 0.02):
        self.lidar: LidarInterface = lidar
        self.state: RobotState = state
        self.poll_interval: float = poll_interval

        lidar_config = config.get("lidar", {})
        buffer_bytes = lidar_config.get("buffer_bytes", 1_048_576)
        overwrite_mode = LidarBufferOverwriteMode(lidar_config.get("overwrite_mode", "ring"))

        self.state.lidar_point_buffer = LidarPointBuffer(
            capacity_bytes=buffer_bytes,
            mode=overwrite_mode,
        )

        # Ciagla decymacja: kazdy cykl skanowania (~cloud_scan_num paczek x 120
        # punktow, tak jak POINTCLOUD w oficjalnym SDK) jest redukowany do
        # decimate_target punktow - bez pomijania co drugiego cyklu, wiec
        # bufor nigdy nie akumuluje pelnych chmur. Decymacja jest strumieniowa
        # (CycleDecimator) - kazda partia z read_points() jest redukowana i
        # dodawana do bufora natychmiast, bez czekania na zebranie calego
        # cyklu, wiec efekt widac od razu przy kazdym pollu (domyslnie co 20ms).
        self.decimate_enabled: bool = lidar_config.get("decimate_enabled", True)
        points_per_packet = lidar_config.get("points_per_packet", 120)
        cloud_scan_num = lidar_config.get("cloud_scan_num", 18)
        cycle_points = lidar_config.get("cycle_points", points_per_packet * cloud_scan_num)
        decimate_target = lidar_config.get("decimate_target", 200)
        self._decimator = CycleDecimator(cycle_points=cycle_points, target_count=decimate_target)

        self.running: bool = False
        self.task: asyncio.Task | None = None

    async def run(self):
        loop = asyncio.get_running_loop()

        while self.running:
            points = await loop.run_in_executor(None, self.lidar.read_points)

            if points:
                if self.decimate_enabled:
                    points = self._decimator.process(points)

                if points:
                    self.state.lidar_point_buffer.add_points(points)

            await asyncio.sleep(self.poll_interval)

    def start(self):
        if self.running:
            return

        self.lidar.start()

        self.running = True
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        self.running = False

        if self.task is not None:
            await self.task

        self.lidar.stop()
