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


class VoiceStateRecordingTests(unittest.TestCase):
    def test_handle_text_records_heard_text_and_matched_action(self):
        state = RobotState()
        voice = Voice(state=state, model_path="unused", logs=False)

        voice._handle_text("jedziemy do przodu")

        self.assertEqual(state.voice_recognition_state.last_text, "jedziemy do przodu")
        self.assertEqual(state.voice_recognition_state.last_action, "▲  DO PRZODU")
        self.assertEqual(len(state.voice_recognition_state.history), 1)

    def test_handle_text_records_unmatched_text_without_action(self):
        state = RobotState()
        voice = Voice(state=state, model_path="unused", logs=False)

        voice._handle_text("coś niezrozumiałego")

        self.assertEqual(state.voice_recognition_state.last_text, "coś niezrozumiałego")
        self.assertIsNone(state.voice_recognition_state.last_action)

    def test_history_is_capped_at_limit(self):
        from src.ai.voice import VOICE_HISTORY_LIMIT

        state = RobotState()
        voice = Voice(state=state, model_path="unused", logs=False)

        for i in range(VOICE_HISTORY_LIMIT + 5):
            voice._handle_text(f"stop {i}")

        self.assertEqual(len(state.voice_recognition_state.history), VOICE_HISTORY_LIMIT)
        self.assertEqual(
            state.voice_recognition_state.history[-1]["text"],
            f"stop {VOICE_HISTORY_LIMIT + 4}",
        )


class VoicePartialResultTests(unittest.TestCase):
    def test_handle_partial_matches_command_without_waiting_for_silence(self):
        """Krotkie komendy w halasie moga nigdy nie sfinalizowac (Vosk czeka
        na cisze) - partial pozwala zareagowac zanim to nastapi."""
        state = RobotState()
        voice = Voice(state=state, model_path="unused", logs=False)

        voice._handle_partial("stój")

        self.assertEqual(state.voice_recognition_state.last_action, "■  STOP")
        self.assertEqual(len(state.voice_recognition_state.history), 1)

    def test_handle_partial_updates_last_text_without_matched_command(self):
        state = RobotState()
        voice = Voice(state=state, model_path="unused", logs=False)

        voice._handle_partial("jed")

        self.assertEqual(state.voice_recognition_state.last_text, "jed")
        self.assertIsNone(state.voice_recognition_state.last_action)
        self.assertEqual(len(state.voice_recognition_state.history), 0)

    def test_handle_partial_respects_debounce_like_handle_text(self):
        state = RobotState()
        voice = Voice(state=state, model_path="unused", logs=False)

        voice._handle_partial("stop")
        voice._handle_partial("stop teraz")

        self.assertEqual(len(state.voice_recognition_state.history), 1)


if __name__ == "__main__":
    unittest.main()
