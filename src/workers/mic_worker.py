import asyncio

from src.hardware.respeaker.interface import MicArrayInterface
from src.hardware.device_slot import resolve
from src.robot_state import RobotState

class MicWorker:
    def __init__(self, mic_array: MicArrayInterface, state: RobotState):
        self.mic_array = mic_array
        self.state: RobotState = state

        self.running: bool = False
        self.task: asyncio.Task | None = None

    async def run(self):
        loop = asyncio.get_running_loop()

        while self.running:
            try:
                chunk = await loop.run_in_executor(None, resolve(self.mic_array).get_audio_chunk)
            except Exception as exc:
                # Bez tego try/except wyjatek z realnego sprzetu (np. stream
                # audio padajacy przy odlaczeniu mikrofonu) ubijalby cala
                # petle na stale (patrz ten sam problem naprawiony w
                # CameraWorker/LidarWorker).
                print(f"Mic read error: {exc}")
                chunk = None

            if chunk is not None:
                self.state.last_audio_chunk = chunk

            await asyncio.sleep(0.001)

    def start(self):
        if self.running:
            return

        resolve(self.mic_array).start()

        self.running = True
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        self.running = False

        if self.task is not None:
            await self.task

        resolve(self.mic_array).stop()
