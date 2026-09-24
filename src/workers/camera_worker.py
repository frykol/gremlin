import asyncio

from src.hardware.oak_d.interface import CameraInterface
from src.hardware.device_slot import resolve
from src.robot_state import RobotState

class CameraWorker:
    def __init__(self, camera: CameraInterface, state: RobotState):
        self.camera = camera
        self.state: RobotState = state

        self.running: bool = False
        self.task: asyncio.Task | None = None

    async def run(self):
        while self.running:
            try:
                frame = resolve(self.camera).get_camera_frame()
            except Exception as exc:
                # Wyjatek z realnego sprzetu (np. depthai/USB zrywajace
                # polaczenie w trakcie odczytu) nie moze ubijac calej petli -
                # bez tego try/except cala petla umierala na stale i nigdy
                # wiecej nie odpytywalaby urzadzenia, nawet po tym jak
                # DeviceMonitor podstawilby dzialajacy dummy albo odzyskana
                # kamere. Podglad zostawal wtedy zamrozony na ostatniej
                # klatce na zawsze, bez wzgledu na kolejne podmiany w slocie.
                print(f"Camera read error: {exc}")
                frame = None

            if frame is not None:
                self.state.last_frame = frame

            await asyncio.sleep(0.001)

    def start(self):
        if self.running:
            return

        resolve(self.camera).start()

        self.running = True
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        self.running = False

        if self.task is not None:
            await self.task

        resolve(self.camera).stop()