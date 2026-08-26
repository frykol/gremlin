import asyncio

from src.hardware.ads1115.interface import ADS1115Interface
from src.robot_state import RobotState, ADS1115State

class ADS1115Worker:
    def __init__(self, ads1115: ADS1115Interface, state: RobotState, poll_interval: float = 0.1):
        self.ads1115: ADS1115Interface = ads1115
        self.state: RobotState = state
        self.poll_interval: float = poll_interval

        self.running: bool = False
        self.task: asyncio.Task | None = None

    async def run(self):
        loop = asyncio.get_running_loop()

        while self.running:
            try:
                channels = await loop.run_in_executor(None, self.ads1115.read_channels)
            except Exception as exc:
                print(f"ADS1115 read error: {exc}")
                channels = None

            if channels is not None:
                (raw_a0, a0), (raw_a1, a1), (raw_a2, a2), (raw_a3, a3) = channels
                self.state.last_ads1115_state = ADS1115State(
                    a0=a0, a1=a1, a2=a2, a3=a3,
                    raw_a0=raw_a0, raw_a1=raw_a1, raw_a2=raw_a2, raw_a3=raw_a3,
                )

            await asyncio.sleep(self.poll_interval)

    def start(self):
        if self.running:
            return

        self.ads1115.start()

        self.running = True
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        self.running = False

        if self.task is not None:
            await self.task

        self.ads1115.stop()
