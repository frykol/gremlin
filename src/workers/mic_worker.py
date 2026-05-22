import asyncio

from src.hardware.respeaker.interface import MicArrayInterface
from src.robot_state import RobotState

class MicWorker:
    def __init__(self, mic_array: MicArrayInterface, state: RobotState):
        self.mic_array: MicArrayInterface = mic_array
        self.state: RobotState = state

        self.running: bool = False
        self.task: asyncio.Task | None = None

    async def run(self):
        while self.running:
            chunk = self.mic_array.get_audio_chunk()

            if chunk is not None:
                self.state.last_audio_chunk = chunk

            await asyncio.sleep(0.001)

    def start(self):
        if self.running:
            return

        self.mic_array.start()

        self.running = True
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        self.running = False

        if self.task is not None:
            await self.task

        self.mic_array.stop()
