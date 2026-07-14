import argparse
import asyncio
import json
import time

import numpy as np
from vosk import Model, KaldiRecognizer

from ..hardware.respeaker.interface import MicArrayInterface

# ─────────────────────────────────────────────
# KONFIGURACJA KOMEND
# ─────────────────────────────────────────────

COMMANDS = {
    "forward": [
        "przód"
    ],
    "backward": [
        "tył",
    ],
    # full_left/full_right (strafe boczny) — hasla, nie opisowe frazy.
    "full_left": [
        "cała w lewo", "cała lewo"
    ],
    "full_right": [
        "cała w prawo", "cała prawo"
    ],
    "left": [
        "w lewo", "lewo"
    ],
    "right": [
        "w prawo", "prawo"
    ],
    "stop": [
        "stój", "stop"
    ],
    "spin": [
        "obrót", "koło"
    ],
    "speed_up": [
        "szybciej"
    ],
    "slow_down": [
        "wolniej"
    ],
}

# Etykiety wyświetlane w logu
LABELS = {
    "forward":    "▲  DO PRZODU",
    "backward":   "▼  DO TYŁU",
    "left":       "◄  W LEWO",
    "right":      "►  W PRAWO",
    "full_left":  "◄◄ FULL LEWO (bok)",
    "full_right": "►► FULL PRAWO (bok)",
    "stop":       "■  STOP",
    "spin":       "↻  OBRÓT 360°",
    "speed_up":   "⚡ SZYBCIEJ",
    "slow_down":  "🐢 WOLNIEJ",
}

# GRAMMAR = json.dumps([
#     "do przodu", "naprzód", "jedź", "jazda", "ruszaj",
#     "do tyłu", "wstecz", "cofnij", "tył", "cofaj",
#     "cała w lewo", "ful lewo",
#     "cała w prawo", "ful prawo",
#     "w lewo", "lewo",
#     "w prawo", "prawo",
#     "stój", "stop", "zatrzymaj", "hamuj", "koniec",
#     "obrót", "obróć się", "spin",
#     "szybciej", "przyspiesz",
#     "wolniej", "zwolnij"
# ])

DEBOUNCE = 1.5  # sekundy — minimalna przerwa między tą samą komendą

# Parametry ruchu (linear/angular). BASE_ANGULAR dobrany tak, zeby predkosc
# kola przy skrecie byla podobna do predkosci przy jezdzie prosto (~30% duty)
# — przy zbyt niskiej wartosci skret nie ma dosc mocy zeby pokonac tarcie.
BASE_LINEAR = 0.3
BASE_ANGULAR = 1.5
SPIN_ANGULAR = 2.0
SPEED_STEP = 1.2
MIN_SPEED_SCALE = 0.3
MAX_SPEED_SCALE = 2.0


# ─────────────────────────────────────────────
# ROZPOZNAWANIE KOMEND
# ─────────────────────────────────────────────

def match_command(text: str):
    """Dopasuj rozpoznany tekst do komendy. Zwraca nazwę akcji lub None."""
    text = text.lower().strip()
    for action, phrases in COMMANDS.items():
        for phrase in phrases:
            if phrase in text:
                return action
    return None


class VoiceWorker:
    def __init__(self, mic_array: MicArrayInterface, model_path: str):
        self.mic_array: MicArrayInterface = mic_array

        self.running: bool = False
        self.task: asyncio.Task | None = None

        self._speed_scale = 1.0
        self._last_action = None
        self._last_time = 0.0

        print(f'Ładowanie modelu: {model_path} ...')
        self._model = Model(model_path)
        self._recognizer = KaldiRecognizer(self._model, 16000)
        self._recognizer.SetWords(True)
        print('Model załadowany.')

    async def run(self):
        loop = asyncio.get_running_loop()

        while self.running:
            chunk = await loop.run_in_executor(None, self.mic_array.get_audio_chunk)

            if chunk is not None:
                data = np.asarray(chunk.samples).astype(np.int16).tobytes()
                if self._recognizer.AcceptWaveform(data):
                    result = json.loads(self._recognizer.Result())
                    text = result.get('text', '').strip()
                    if text:
                        self._handle_text(text)

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

    def _handle_text(self, text: str):
        print(f'[słyszę] "{text}"')
        action = match_command(text)
        if action is None:
            print('[?] Nie rozpoznano komendy.')
            return

        now = time.monotonic()
        if action == self._last_action and (now - self._last_time) < DEBOUNCE:
            return
        self._last_action = action
        self._last_time = now

        print(LABELS.get(action, action))
        self._apply_action(action)

    def _apply_action(self, action: str):
        if action == 'speed_up':
            self._speed_scale = min(MAX_SPEED_SCALE, self._speed_scale * SPEED_STEP)
            return
        if action == 'slow_down':
            self._speed_scale = max(MIN_SPEED_SCALE, self._speed_scale / SPEED_STEP)
            return

        linear_x = 0.0
        linear_y = 0.0
        angular_z = 0.0

        if action == 'forward':
            linear_x = BASE_LINEAR * self._speed_scale
        elif action == 'backward':
            linear_x = -BASE_LINEAR * self._speed_scale
        elif action == 'left':
            angular_z = BASE_ANGULAR * self._speed_scale
        elif action == 'right':
            angular_z = -BASE_ANGULAR * self._speed_scale
        elif action == 'full_left':
            linear_y = BASE_LINEAR * self._speed_scale
        elif action == 'full_right':
            linear_y = -BASE_LINEAR * self._speed_scale
        elif action == 'spin':
            angular_z = SPIN_ANGULAR * self._speed_scale
        # 'stop' -> zostaja same zera

        print(f'[ruch] linear_x={linear_x:.2f} linear_y={linear_y:.2f} angular_z={angular_z:.2f}')


def main(args=None):
    parser = argparse.ArgumentParser(
        description="Sterowanie robotem głosem (Vosk, offline)"
    )
    parser.add_argument(
        '--model', default='/robot/model',
        help='Ścieżka do folderu z modelem Vosk'
    )
    parser.add_argument(
        '--device-name', default='ReSpeaker 4 Mic Array',
        help='Nazwa (fragment) urządzenia audio do wyszukania.'
    )
    parser.add_argument(
        '--dummy', action='store_true',
        help='Uzyj FakeReSpeakerMicArray zamiast prawdziwego mikrofonu.'
    )
    parsed = parser.parse_args(args)

    if parsed.dummy:
        from ..hardware.respeaker.dummy_respeaker import FakeReSpeakerMicArray
        mic_array = FakeReSpeakerMicArray()
    else:
        from ..hardware.respeaker.respeaker import ReSpeakerMicArray
        mic_array = ReSpeakerMicArray(device_name=parsed.device_name)

    worker = VoiceWorker(mic_array=mic_array, model_path=parsed.model)

    async def _run():
        worker.start()
        try:
            while worker.running:
                await asyncio.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            await worker.stop()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
