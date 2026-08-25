#!/usr/bin/env python3
"""
Samodzielny, szybki podglad 3D chmury punktow z Unitree LiDAR L1 -
matplotlib zamiast Open3D (ktorego nie da sie zainstalowac na tym
systemie: aarch64 + Python 3.13, brak kompatybilnego wheela).

W przeciwienstwie do propozycji z UDP (unilidar_subcriber_udp.py + Open3D)
ten skrypt laczy sie BEZPOSREDNIO po porcie szeregowym, uzywajac juz
przetestowanego sterownika UnitreeL1Lidar z projektu (ten sam kod, ktory
napedza glowna aplikacje robota) - zero dodatkowej konfiguracji sieciowej
(UDP/porty adaptera), zero zaleznosci od reszty aplikacji robota (nie
wymaga uruchomionego robot_controller/WS - trzeba tylko, zeby port
szeregowy nie byl w tym momencie zajety przez cos innego).

Wymaga dzialajacego backendu GUI matplotlib (np. TkAgg) - jesli laczysz
sie po SSH, dodaj przekierowanie X11 (ssh -X) albo uruchom lokalnie na Pi
z podlaczonym monitorem.

Uzycie:
    python3 preview_lidar_3d.py [--port /dev/ttyUSB0] [--baud 2000000]
                                 [--range-min 0.05] [--range-max 30]
                                 [--window-cycles 20] [--refresh-hz 5]
"""
import argparse
import signal
import sys
import time
from pathlib import Path

# Sterownik uzywa relatywnych importow (from .interface import ...), wiec
# musi byc zaladowany jako czesc pakietu `src` - dodajemy katalog nadrzedny
# projektu (gremlin/) do sys.path, zeby `import src...` zadzialalo bez
# wzgledu na to, z jakiego katalogu ten skrypt zostal odpalony.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.hardware.lidar.unitree_l1 import UnitreeL1Lidar  # noqa: E402
from src.services.command_processor import _reflectivity_to_color  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=2_000_000)
    parser.add_argument("--range-min", type=float, default=0.05)
    parser.add_argument("--range-max", type=float, default=30.0)
    parser.add_argument("--intensity-max", type=int, default=255)
    parser.add_argument(
        "--window-cycles", type=int, default=20,
        help="Ile ostatnich paczek trzymac w oknie podgladu (wiecej = pelniejszy ksztalt 3D, wolniejszy redraw).",
    )
    parser.add_argument("--refresh-hz", type=float, default=5.0, help="Czestosc odswiezania okna.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        import matplotlib.pyplot as plt  # import po parse_args, zeby --help dzialalo bez GUI
    except ModuleNotFoundError:
        print(
            "Brak modulu matplotlib w tym interpreterze Pythona.\n"
            "Ten projekt trzyma zaleznosci w venv - uruchom skrypt przez:\n"
            "  .venv/bin/python3 lidar_test/preview_lidar_3d.py [opcje]\n"
            "albo najpierw: source .venv/bin/activate",
            file=sys.stderr,
        )
        return 1

    _NON_INTERACTIVE_BACKENDS = {"agg", "pdf", "ps", "svg", "cairo", "template"}
    if plt.get_backend().lower() in _NON_INTERACTIVE_BACKENDS:
        print(
            f"Matplotlib uzywa headless backendu '{plt.get_backend()}' - okno NIE "
            "pokaze sie nigdzie (to nie blad, po prostu brak serwera X/VNC w tej "
            "sesji, np. SSH/VSCode remote bez X11 forwarding). Zanim uruchomisz "
            "ponownie:\n"
            "  - polacz sie z 'ssh -X' (wymaga X server po Twojej stronie, np. "
            "XQuartz/VcXsrv), albo\n"
            "  - postaw VNC/remote desktop na tym Pi i polącz sie przez to, albo\n"
            "  - uzyj zamiast tego istniejacego dashboardu w przegladarce "
            "(site/public) - dziala przez siec bez X11.",
            file=sys.stderr,
        )
        return 1

    lidar = UnitreeL1Lidar(
        port=args.port,
        baud=args.baud,
        range_min=args.range_min,
        range_max=args.range_max,
        intensity_max=args.intensity_max,
    )

    print(f"Laczenie z {args.port} @ {args.baud} baud...")
    lidar.start()  # wysyla tez NORMAL (patrz set_working_mode w unitree_l1.py)
    print("Polaczono, tryb NORMAL wyslany. Ctrl+C aby zakonczyc.")

    keep_running = True

    def handle_sigint(signum, frame):
        nonlocal keep_running
        keep_running = False

    signal.signal(signal.SIGINT, handle_sigint)

    plt.ion()
    fig = plt.figure(figsize=(8, 8))
    ax = fig.add_subplot(111, projection="3d")
    ax.set_xlabel("x (prawo) [m]")
    ax.set_ylabel("y (przod) [m]")
    ax.set_zlabel("z (gora) [m]")
    scatter = ax.scatter([], [], [], s=4)

    window: list[tuple[float, float, float, int]] = []
    refresh_interval = 1.0 / max(args.refresh_hz, 0.1)
    next_refresh = time.monotonic()

    try:
        while keep_running:
            points = lidar.read_points()
            if points:
                window.extend(points)
                # Utrzymuj tylko ostatnie N cykli - przyblizenie przez limit
                # liczby punktow (do 120 punktow na kazda paczke aux+dist).
                max_points = args.window_cycles * 120
                if len(window) > max_points:
                    window = window[-max_points:]

            now = time.monotonic()
            if now >= next_refresh and window:
                xs = [p[0] for p in window]
                ys = [p[1] for p in window]
                zs = [p[2] for p in window]
                colors = [_reflectivity_to_color(p[3]) for p in window]

                scatter._offsets3d = (xs, ys, zs)
                scatter.set_color(colors)
                ax.set_title(f"{len(window)} punktow (okno {args.window_cycles} cykli)")

                # Autoskalowanie osi do biezacych danych.
                pad = 0.5
                ax.set_xlim(min(xs) - pad, max(xs) + pad)
                ax.set_ylim(min(ys) - pad, max(ys) + pad)
                ax.set_zlim(min(zs) - pad, max(zs) + pad)

                fig.canvas.draw_idle()
                fig.canvas.flush_events()
                next_refresh = now + refresh_interval

            plt.pause(0.001)  # oddaje sterowanie petli zdarzen GUI
    finally:
        print("\nZamykanie - wysylam STANDBY i zamykam port...")
        lidar.stop()
        plt.ioff()

    return 0


if __name__ == "__main__":
    sys.exit(main())
