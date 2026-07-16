import asyncio

from src.hardware.lidar.interface import LidarInterface
from src.robot_state import RobotState, LidarPointBuffer, LidarBufferOverwriteMode


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

        self.running: bool = False
        self.task: asyncio.Task | None = None

    async def run(self):
        loop = asyncio.get_running_loop()

        while self.running:
            points = await loop.run_in_executor(None, self.lidar.read_points)

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
