import asyncio

from src.hardware.gpio.encoder_controller import EncoderController
from src.robot_state import RobotState, EncoderState


class EncoderWorker:
    """Publikuje odczyty EncoderController do RobotState, zeby inne moduly
    mialy do nich latwy, nieblokujacy dostep (bez sięgania po gpiod)."""

    def __init__(self, encoder: EncoderController, state: RobotState, publish_interval: float = 0.05):
        self.encoder: EncoderController = encoder
        self.state: RobotState = state
        self.publish_interval: float = publish_interval

        self.state.encoder_state = EncoderState()

        self.running: bool = False
        self.task: asyncio.Task | None = None

    async def run(self):
        while self.running:
            self.state.encoder_state.ticks = self.encoder.get_all_ticks()
            await asyncio.sleep(self.publish_interval)

    def start(self):
        if self.running:
            return

        self.encoder.start()

        self.running = True
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        self.running = False

        if self.task is not None:
            await self.task

        self.encoder.stop()
