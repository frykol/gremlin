"""Jesli realny sprzet rzuci wyjatek w trakcie odczytu (np. depthai/USB
zrywajace polaczenie, port szeregowy znikajacy przy odlaczeniu, padajacy
stream audio), petla run() workera NIE MOZE sie na tym wywalic na stale -
niezlapany wyjatek w tasku asyncio cichutko go zabija i worker juz nigdy
wiecej nie odpytalby urzadzenia, nawet po tym jak DeviceMonitor podstawilby
w miedzyczasie dzialajacy dummy albo odzyskane realne urzadzenie. Testuje, ze
worker przezywa pojedynczy blad odczytu i wraca do normalnego dzialania przy
kolejnej iteracji."""

import asyncio

from src.robot_state import RobotState
from src.workers.camera_worker import CameraWorker
from src.workers.lidar_worker import LidarWorker
from src.workers.mic_worker import MicWorker


class FlakyCamera:
    def __init__(self):
        self.calls = 0

    def start(self):
        pass

    def stop(self):
        pass

    def get_camera_frame(self):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("Communication exception - possible device error")
        return f"frame-{self.calls}"


class FlakyLidar:
    def __init__(self):
        self.calls = 0

    def start(self):
        pass

    def stop(self):
        pass

    def read_points(self):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("serial port gone")
        return [(1.0, 2.0, 3.0, 100)]


class FlakyMic:
    def __init__(self):
        self.calls = 0

    def start(self):
        pass

    def stop(self):
        pass

    def get_audio_chunk(self):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("stream closed")
        return f"chunk-{self.calls}"


async def _run_worker_briefly(worker):
    worker.start()
    await asyncio.sleep(0.05)
    worker.running = False
    if worker.task is not None:
        await worker.task


def test_camera_worker_survives_read_error_and_keeps_polling():
    async def scenario():
        camera = FlakyCamera()
        state = RobotState()
        worker = CameraWorker(camera=camera, state=state)

        await _run_worker_briefly(worker)

        assert camera.calls > 1
        assert state.last_frame is not None

    asyncio.run(scenario())


def test_lidar_worker_survives_read_error_and_keeps_polling():
    async def scenario():
        lidar = FlakyLidar()
        state = RobotState()
        worker = LidarWorker(lidar=lidar, state=state, config={}, poll_interval=0.001)

        await _run_worker_briefly(worker)

        assert lidar.calls > 1
        assert len(state.lidar_point_buffer) > 0

    asyncio.run(scenario())


def test_mic_worker_survives_read_error_and_keeps_polling():
    async def scenario():
        mic = FlakyMic()
        state = RobotState()
        worker = MicWorker(mic_array=mic, state=state)

        await _run_worker_briefly(worker)

        assert mic.calls > 1
        assert state.last_audio_chunk is not None

    asyncio.run(scenario())
