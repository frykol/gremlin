import asyncio

class CameraWorker:
    def __init__(self, camera, state):
        self.camera = camera
        self.state = state

        self.running = False
        self.task = None

    async def run(self):
        while self.running:
            frame = self.camera.get_camera_frame()

            if frame is not None:
                self.state.last_frame = frame

            await asyncio.sleep(0.001)

    def start(self):
        if self.running:
            return

        self.camera.start()

        self.running = True
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        self.running = False

        if self.task is not None:
            await self.task

        self.camera.stop()