import argparse
import json
import threading
import time

import numpy as np
from vosk import Model, KaldiRecognizer

from src.robot_state import RobotState

# ─────────────────────────────────────────────
# KONFIGURACJA KOMEND
# ─────────────────────────────────────────────

COMMANDS = {
    "forward": [
        "przód", "do przodu"
    ],
    "backward": [
        "tył", "do tyłu"
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


class Voice:
    """
    Konsumuje chunki audio z RobotState.last_audio_chunk zamiast czytac
    je bezposrednio z mikrofonu. Dzieki temu Voice moze dzialac
    obok MicWorker (ktory faktycznie odpytuje sprzet) bez rywalizacji
    o ten sam strumien audio.
    """

    def __init__(self, state: RobotState, model_path: str, logs: bool):
        self.state: RobotState = state

        self.running: bool = False
        self.thread: threading.Thread | None = None

        self._speed_scale = 1.0
        self._last_action = None
        self._last_time = 0.0

        # Sluzy do wykrywania, ze pojawil sie nowy chunk w state
        # (unikamy przetwarzania tego samego chunku wielokrotnie).
        self._last_chunk = None
        self._last_partial = ''

        print(f'Ładowanie modelu: {model_path} ...')
        self._model = Model(model_path)
        self._recognizer = KaldiRecognizer(self._model, 16000)
        self._recognizer.SetWords(True)
        print('Model załadowany.')

        self._logs = logs

    def run(self):
        while self.running:
            chunk = self.state.last_audio_chunk

            if chunk is not None and chunk is not self._last_chunk:
                self._last_chunk = chunk

                data = np.asarray(chunk.samples).astype(np.int16).tobytes()
                if self._recognizer.AcceptWaveform(data):
                    result = json.loads(self._recognizer.Result())
                    text = result.get('text', '').strip()
                    if text:
                        self._handle_text(text)
                # else:
                #     partial = json.loads(self._recognizer.PartialResult())
                #     partial_text = partial.get('partial', '').strip()
                #     if partial_text and partial_text != self._last_partial:
                #         self._last_partial = partial_text
                #         print(f'[słucham] "{partial_text}"')
            else:
                # Nie ma jeszcze nowego chunku — nie zajmuj rdzenia w petli.
                time.sleep(0.001)

    def start(self):
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False

        if self.thread is not None:
            self.thread.join()

    def _handle_text(self, text: str):
        if self._logs: print(f'[słyszę] "{text}"')
        action = match_command(text)
        if action is None:
            if self._logs: print('[?] Nie rozpoznano komendy.')
            return

        now = time.monotonic()
        if action == self._last_action and (now - self._last_time) < DEBOUNCE:
            return
        self._last_action = action
        self._last_time = now

        if self._logs: print(LABELS.get(action, action))
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

        if self._logs: print(f'[ruch] linear_x={linear_x:.2f} linear_y={linear_y:.2f} angular_z={angular_z:.2f}')


def main(args=None):
    parser = argparse.ArgumentParser(
        description="Sterowanie robotem głosem (Vosk, offline)"
    )
    parser.add_argument(
        '--model', default='/home/gremlin/gremlin/model',
        help='Ścieżka do folderu z modelem Vosk'
    )
    parsed = parser.parse_args(args)

    # Uwaga: ten CLI nie odpala juz wlasnego MicWorker'a. Voice
    # konsumuje wylacznie RobotState.last_audio_chunk, wiec cos innego
    # (docelowo RobotController, ktory odpala MicWorker i Voice
    # razem) musi ten chunk tam wstawiac. Uruchomienie samego tego
    # pliku bez takiego producenta nie rozpozna zadnej mowy.
    state = RobotState()
    voice = Voice(state=state, model_path=parsed.model)

    voice.start()
    try:
        while voice.running:
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        voice.stop()


if __name__ == '__main__':
    main()