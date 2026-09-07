import asyncio
import subprocess

from src.hardware.ads1115.interface import ADS1115Interface
from src.robot_state import RobotState, ADS1115State

class ADS1115Worker:
    def __init__(
        self,
        ads1115: ADS1115Interface,
        state: RobotState,
        poll_interval: float = 0.1,
        shutdown_min_voltage: float | None = 12,
    ):
        self.ads1115: ADS1115Interface = ads1115
        self.state: RobotState = state
        self.poll_interval: float = poll_interval
        self.shutdown_min_voltage: float | None = shutdown_min_voltage

        self.running: bool = False
        self.task: asyncio.Task | None = None
        self._shutdown_triggered: bool = False

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

                self._check_low_voltage_shutdown(a0)

            await asyncio.sleep(self.poll_interval)

    def _check_low_voltage_shutdown(self, a0: float) -> None:
        if self.shutdown_min_voltage is None or self._shutdown_triggered:
            return

        if a0 >= self.shutdown_min_voltage:
            return

        self._shutdown_triggered = True
        print(
            f"ADS1115: napiecie A0 ({a0:.2f}V) ponizej progu "
            f"({self.shutdown_min_voltage:.2f}V) - wylaczam raspberry"
        )
        try:
            subprocess.run(["sudo", "shutdown", "-h", "now"], check=True)
        except Exception as exc:
            print(f"ADS1115: nie udalo sie wykonac wylaczenia: {exc}")

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
