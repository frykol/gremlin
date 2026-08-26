import asyncio
import sys
import time
import types
import unittest

# Some test modules in this suite install a bare-bones numpy stub into
# sys.modules (no cleanup) to keep unrelated imports lightweight. If pytest
# collects one of those files first, that stub leaks into every later test
# module's `import numpy`. Voice actually needs real numpy behavior, so
# drop a stub if one is already cached before importing.
if not hasattr(sys.modules.get("numpy"), "zeros"):
    sys.modules.pop("numpy", None)

import numpy as np

vosk_stub = types.ModuleType("vosk")


class _StubModel:
    def __init__(self, path):
        pass


class _StubRecognizer:
    def __init__(self, model, sample_rate):
        pass

    def SetWords(self, value):
        pass

    def AcceptWaveform(self, data):
        return False

    def Result(self):
        return "{}"


vosk_stub.Model = _StubModel
vosk_stub.KaldiRecognizer = _StubRecognizer
sys.modules["vosk"] = vosk_stub

from src.ai.voice import Voice
from src.hardware.respeaker.interface import AudioChunk
from src.robot_state import RobotState


class BlockingRecognizer:
    """Symuluje wolne, blokujace CPU rozpoznawanie mowy (jak prawdziwy Vosk)."""

    def __init__(self, delay: float):
        self.delay = delay
        self.calls = 0

    def AcceptWaveform(self, data):
        self.calls += 1
        time.sleep(self.delay)
        return True

    def Result(self):
        return '{"text": ""}'


def make_chunk(chunk_id: int) -> AudioChunk:
    return AudioChunk(
        samples=np.zeros(160, dtype=np.int16),
        timestamp=0.0,
        sample_rate=16000,
        channels=1,
        chunk_id=chunk_id,
    )


class VoiceNonBlockingTests(unittest.IsolatedAsyncioTestCase):
    async def test_recognizer_call_does_not_block_event_loop(self):
        state = RobotState()
        voice = Voice(state=state, model_path="unused", logs=False)
        voice._recognizer = BlockingRecognizer(delay=0.2)
        state.last_audio_chunk = make_chunk(1)

        voice_task = asyncio.create_task(voice.run())

        start = time.perf_counter()
        for _ in range(10):
            await asyncio.sleep(0.02)
        elapsed = time.perf_counter() - start

        voice_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await voice_task

        # 10 * 0.02s = 0.2s of scheduled wakeups. If the recognizer's
        # blocking 0.2s call runs on the event loop's own thread, it
        # starves these wakeups and elapsed balloons past 0.3s. If it is
        # offloaded (asyncio.to_thread), elapsed stays close to 0.2s.
        self.assertLess(elapsed, 0.3)
        self.assertGreaterEqual(voice._recognizer.calls, 1)


if __name__ == "__main__":
    unittest.main()
