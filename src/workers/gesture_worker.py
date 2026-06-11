import asyncio

from src.robot_state import RobotState
from src.services.gesture_executor import GestureExecutor
from src.services.hand_gestures import HandGestureDetector


class GestureWorker:
    def __init__(
        self,
        state: RobotState,
        detector: HandGestureDetector,
        executor: GestureExecutor,
    ):
        self.state = state
        self.detector = detector
        self.executor = executor
        self.running = False
        self.task: asyncio.Task | None = None
        self._last_printed: str | None = None

    async def run(self):
        loop = asyncio.get_running_loop()

        while self.running:
            frame = self.state.last_frame
            if frame is None:
                await asyncio.sleep(0.01)
                continue

            gestures, results = await loop.run_in_executor(
                None,
                self.detector.process,
                frame.image.copy(),
            )

            display = frame.image.copy()
            self.detector.draw(display, results)

            primary = gestures[0] if gestures else None
            self.detector.draw_command(display, primary)

            self.state.display_frame = display
            self.state.last_gestures = gestures
            self.state.gesture_name = primary.gesture_name if primary else "brak"

            if primary:
                if primary.gesture_name == "ok":
                    label = "Gest: ok"
                else:
                    label = f"Gest: {primary.gesture_name} ({primary.finger_count})"
                if label != self._last_printed:
                    print(label)
                    self.executor.handle(primary.finger_count, primary.gesture_name)
                    self._last_printed = label
            elif self._last_printed is not None:
                self._last_printed = None
                print("Gest: brak")

            await asyncio.sleep(0.001)

    def start(self):
        if self.running:
            return

        self.running = True
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        self.running = False

        if self.task is not None:
            await self.task

        self.detector.close()
