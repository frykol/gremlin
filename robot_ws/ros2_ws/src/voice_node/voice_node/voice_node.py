"""
Robot Voice Control - sterowanie glosowe robotem mobilnym (ROS2 node)
Silnik: Vosk (offline AI, jezyk polski)

Oparte na oryginalnym skrypcie CLI Norberta. Komendy, etykiety i logika
dopasowania (match_command) sa przeniesione bez zmian; zamiast drukowac
akcje w konsoli, node publikuje Twist na /cmd_vel_voice.

Dopisek integracyjny: motor_driver ma watchdog 300ms (patrz
motor_driver.py), a rozpoznana komenda glosowa przychodzi rzadko (raz na
DEBOUNCE sekund), wiec ostatnia aktywna komenda jest republikowana w tle
az do nastepnej komendy — bez tego robot zatrzymywalby sie ~300ms po
kazdym "do przodu".
"""

import argparse
import array
import json
import queue
import sys
import threading
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist

import sounddevice as sd
from vosk import Model, KaldiRecognizer

# ─────────────────────────────────────────────
# KONFIGURACJA KOMEND
# ─────────────────────────────────────────────

COMMANDS = {
    "forward": [
        "do przodu", "naprzód", "jedź", "jedz", "jazda",
        "ruszaj"
    ],
    "backward": [
        "do tyłu", "wstecz", "cofnij", "tył", "cofaj",
    ],
    # full_left/full_right (strafe boczny) — hasla, nie opisowe frazy.
    "full_left": [
        "cała w lewo", "ful lewo"
    ],
    "full_right": [
        "cała w prawo", "ful prawo"
    ],
    "left": [
        "w lewo", "lewo"
    ],
    "right": [
        "w prawo", "prawo"
    ],
    "stop": [
        "stój", "stop", "zatrzymaj",
        "hamuj", "koniec"
    ],
    "spin": [
        "obrót", "obróć się", "spin"
    ],
    "speed_up": [
        "szybciej", "przyspiesz"
    ],
    "slow_down": [
        "wolniej", "zwolnij",
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

DEBOUNCE = 1.5  # sekundy — minimalna przerwa między tą samą komendą

# Parametry ruchu (Twist) i republikacji.
# BASE_ANGULAR dobrany tak, zeby predkosc kola przy skrecie (k*wz/WHEEL_RADIUS_M
# w motor_driver.py) byla podobna do predkosci przy jezdzie prosto (~30% duty)
# — przy zbyt niskiej wartosci skret nie ma dosc mocy zeby pokonac tarcie.
BASE_LINEAR = 0.3
BASE_ANGULAR = 1.5
SPIN_ANGULAR = 2.0
SPEED_STEP = 1.2
MIN_SPEED_SCALE = 0.3
MAX_SPEED_SCALE = 2.0
REPUBLISH_RATE_HZ = 10.0  # > watchdog 300ms w motor_driver
MOVE_DURATION_S = 1.0  # po tylu sekundach ruch sam sie zatrzymuje

# ReSpeaker 4 Mic Array (UAC1.0) wystawia się jako urządzenie 6-kanałowe:
# kanał 0 = przetworzone/beamformed audio, 1-4 = surowe mikrofony,
# 5 = referencja do echo-cancellation. Zmierzone RMS: ch0 ~2780 (głos),
# ch1-4 ~210 (szum tła), ch5 = 0 (cisza). Wymuszenie 1 kanału na `hw:`
# dawało pusty strumień, więc nagrywamy wszystkie 6 i wybieramy kanał 0.
MIC_CHANNELS = 6
VOICE_CHANNEL_INDEX = 0


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


def find_respeaker_device():
    """Znajdz indeks PortAudio urzadzenia ReSpeaker po nazwie.

    Numeracja PortAudio potrafi sie przesunac miedzy ros2 run a ros2 launch
    (inna kolejnosc enumeracji ALSA w zaleznosci od kontekstu procesu),
    wiec sztywny numer indeksu jest kruchy — szukamy po nazwie zamiast tego.
    """
    for idx, dev in enumerate(sd.query_devices()):
        if dev.get('max_input_channels', 0) > 0 and 'respeaker' in dev.get('name', '').lower():
            return idx
    return None


class VoiceNode(Node):

    def __init__(self, model_path: str, device):
        super().__init__('voice_node')
        self.publisher_ = self.create_publisher(Twist, '/cmd_vel_voice', 10)

        grammar = json.dumps([
            "do przodu", "naprzód", "jedź", "jazda", "ruszaj",
            "do tyłu", "wstecz", "cofnij", "tył", "cofaj",
            "cała w lewo", "ful lewo",
            "cała w prawo", "ful prawo",
            "w lewo", "lewo",
            "w prawo", "prawo",
            "stój", "stop", "zatrzymaj", "hamuj", "koniec",
            "obrót", "obróć się", "spin",
            "szybciej", "przyspiesz",
            "wolniej", "zwolnij"
        ])

        self._speed_scale = 1.0
        self._current_twist = Twist()
        self._last_action = None
        self._last_time = 0.0
        self._stop_timer = None

        self.get_logger().info(f'Ładowanie modelu: {model_path} ...')
        self._model = Model(model_path)
        self._recognizer = KaldiRecognizer(self._model, 16000, grammar)
        self._recognizer.SetWords(True)
        self.get_logger().info('Model załadowany.')

        if device is None:
            device = find_respeaker_device()
            if device is None:
                raise RuntimeError('Nie znaleziono urzadzenia ReSpeaker (sd.query_devices()).')
            self.get_logger().info(f'Auto-wykryto ReSpeaker: urzadzenie #{device}')
        else:
            self.get_logger().info(f'Uzywam urzadzenia audio #{device} (podane recznie)')
        self._device = device
        self._audio_queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._listen_thread.start()

        self._timer = self.create_timer(1.0 / REPUBLISH_RATE_HZ, self._republish)

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            self.get_logger().warn(str(status))
        samples = array.array('h')
        samples.frombytes(bytes(indata))
        mono = samples[VOICE_CHANNEL_INDEX::MIC_CHANNELS]
        self._audio_queue.put(mono.tobytes())

    def _listen_loop(self):
        with sd.RawInputStream(
            samplerate=16000,
            blocksize=4000,
            device=self._device,
            dtype='int16',
            channels=MIC_CHANNELS,
            callback=self._audio_callback,
        ):
            self.get_logger().info('Nasłuchiwanie...')
            while not self._stop_event.is_set() and rclpy.ok():
                data = self._audio_queue.get()
                if self._recognizer.AcceptWaveform(data):
                    result = json.loads(self._recognizer.Result())
                    for w in result.get("result", []):
                        print(w["word"], w["conf"])
                    text = result.get('text', '').strip()
                    if text:
                        self._handle_text(text)
                else:
                    partial = json.loads(self._recognizer.PartialResult())
                    text = partial.get("partial", "").strip()

    def _handle_text(self, text: str):
        self.get_logger().info(f'[słyszę] "{text}"')
        action = match_command(text)
        if action is None:
            self.get_logger().info('[?] Nie rozpoznano komendy.')
            return

        now = time.monotonic()
        if action == self._last_action and (now - self._last_time) < DEBOUNCE:
            return
        self._last_action = action
        self._last_time = now

        self.get_logger().info(LABELS.get(action, action))
        self._apply_action(action)

    def _apply_action(self, action: str):
        if action == 'speed_up':
            self._speed_scale = min(MAX_SPEED_SCALE, self._speed_scale * SPEED_STEP)
            return
        if action == 'slow_down':
            self._speed_scale = max(MIN_SPEED_SCALE, self._speed_scale / SPEED_STEP)
            return

        if self._stop_timer is not None:
            self._stop_timer.cancel()
            self._stop_timer = None

        twist = Twist()
        if action == 'forward':
            twist.linear.x = BASE_LINEAR * self._speed_scale
        elif action == 'backward':
            twist.linear.x = -BASE_LINEAR * self._speed_scale
        elif action == 'left':
            twist.angular.z = BASE_ANGULAR * self._speed_scale
        elif action == 'right':
            twist.angular.z = -BASE_ANGULAR * self._speed_scale
        elif action == 'full_left':
            twist.linear.y = BASE_LINEAR * self._speed_scale
        elif action == 'full_right':
            twist.linear.y = -BASE_LINEAR * self._speed_scale
        elif action == 'spin':
            twist.angular.z = SPIN_ANGULAR * self._speed_scale
        # 'stop' -> zostaje zerowy Twist()

        self._current_twist = twist
        self.publisher_.publish(twist)

        if action != 'stop':
            self._stop_timer = threading.Timer(MOVE_DURATION_S, self._auto_stop)
            self._stop_timer.daemon = True
            self._stop_timer.start()

    def _auto_stop(self):
        self._current_twist = Twist()
        self.publisher_.publish(self._current_twist)

    def _republish(self):
        self.publisher_.publish(self._current_twist)

    def destroy_node(self):
        self._stop_event.set()
        if self._stop_timer is not None:
            self._stop_timer.cancel()
        super().destroy_node()


def list_devices():
    print(sd.query_devices())


def main(args=None):
    parser = argparse.ArgumentParser(
        description="Sterowanie robotem głosem (Vosk, offline)"
    )
    parser.add_argument(
        '--model', default='/robot/model',
        help='Ścieżka do folderu z modelem Vosk (w kontenerze: /robot/model)'
    )
    parser.add_argument(
        '--device', default=None,
        help='Numer urządzenia audio (mikrofonu). Domyślnie: auto-wykrywanie ReSpeakera.'
    )
    parser.add_argument(
        '--list-devices', action='store_true',
        help='Wypisz dostępne urządzenia audio i wyjdź.'
    )
    parsed, _ = parser.parse_known_args(args if args is not None else sys.argv[1:])

    if parsed.list_devices:
        list_devices()
        return

    try:
        device = int(parsed.device) if parsed.device is not None else None
    except ValueError:
        device = None  # np. pusty string / "auto" z launch — wymusza auto-wykrywanie

    rclpy.init(args=None)
    node = VoiceNode(model_path=parsed.model, device=device)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
