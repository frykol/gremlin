import argparse
import asyncio
import json
import time

import numpy as np
from vosk import Model, KaldiRecognizer

from src.robot_state import RobotState, VoiceRecognitionState

VOICE_HISTORY_LIMIT = 20

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

        if self.state.voice_recognition_state is None:
            self.state.voice_recognition_state = VoiceRecognitionState()

    async def run(self):
        while True:
            chunk = self.state.last_audio_chunk

            if chunk is not None and chunk is not self._last_chunk:
                self._last_chunk = chunk

                data = np.asarray(chunk.samples).astype(np.int16).tobytes()
                accepted, result_json = await asyncio.to_thread(self._process_chunk, data)
                if accepted:
                    self._last_partial = ''
                    result = json.loads(result_json)
                    text = result.get('text', '').strip()
                    if text:
                        self._handle_text(text)
                else:
                    # Wynik czesciowy (Vosk jeszcze nie wykryl ciszy konczacej
                    # wypowiedz). Bez tego krotkie komendy w halasie (silniki,
                    # lidar) mogly nigdy sie nie sfinalizowac i ginac w calosci
                    # - patrz VoiceStateRecordingTests w tests/test_voice.py.
                    partial = json.loads(result_json).get('partial', '').strip()
                    if partial and partial != self._last_partial:
                        self._last_partial = partial
                        self._handle_partial(partial)
            else:
                # Nie ma jeszcze nowego chunku — nie zajmuj rdzenia w petli.
                await asyncio.sleep(0.001)

    def _process_chunk(self, data: bytes) -> tuple[bool, str]:
        """Blokujace, ciezkie obliczeniowo wywolanie Vosk. Uruchamiane przez
        asyncio.to_thread, zeby nie zamrazac petli zdarzen (a wiec i innych
        taskow, np. CommandProcessor obslugujacego komendy z Control/I2C)."""
        accepted = self._recognizer.AcceptWaveform(data)
        if accepted:
            return True, self._recognizer.Result()
        return False, self._recognizer.PartialResult()

    def _handle_text(self, text: str):
        action = match_command(text)
        self._record_heard(text, action)

        if action is None:
            return

        now = time.monotonic()
        if action == self._last_action and (now - self._last_time) < DEBOUNCE:
            return
        self._last_action = action
        self._last_time = now

        self._apply_action(action)

    def _handle_partial(self, text: str):
        """Dopasowuje komendy juz na wyniku czesciowym, zamiast czekac na
        finalizacje (cisza). Nie zapisuje kazdego czesciowego fragmentu do
        historii w UI (zalewaloby ja narastajacym tekstem typu "w", "w
        prawo") - tylko last_text na biezaco i historie w momencie realnego
        dopasowania komendy."""
        voice_state = self.state.voice_recognition_state
        voice_state.last_text = text
        voice_state.last_update = time.time()

        action = match_command(text)
        if action is None:
            return

        now = time.monotonic()
        if action == self._last_action and (now - self._last_time) < DEBOUNCE:
            return
        self._last_action = action
        self._last_time = now

        label = LABELS.get(action, action)
        voice_state.last_action = label
        voice_state.history.append({'text': text, 'action': label, 'time': voice_state.last_update})
        if len(voice_state.history) > VOICE_HISTORY_LIMIT:
            del voice_state.history[:-VOICE_HISTORY_LIMIT]

        self._apply_action(action)

    def _record_heard(self, text: str, action: str | None):
        """Zapisuje uslyszany tekst do RobotState (do zakladki Glos w UI)
        zamiast drukowac na terminal/log."""
        voice_state = self.state.voice_recognition_state
        now = time.time()

        voice_state.last_text = text
        voice_state.last_action = LABELS.get(action, action) if action else None
        voice_state.last_update = now

        voice_state.history.append({
            'text': text,
            'action': voice_state.last_action,
            'time': now,
        })
        if len(voice_state.history) > VOICE_HISTORY_LIMIT:
            del voice_state.history[:-VOICE_HISTORY_LIMIT]

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

    try:
        asyncio.run(voice.run())
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()