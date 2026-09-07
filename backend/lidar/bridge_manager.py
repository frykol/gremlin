"""
Zarzadza cyklem zycia subprocessu unilidar_publisher_udp (bridge z SDK
Unitree, C++) - to on faktycznie otwiera port szeregowy lidaru i
retransmituje dane po UDP. Bridge sam wysyla komende NORMAL do lidaru po
starcie (zweryfikowane w zrodle unilidar_publisher_udp.cpp), wiec ten
modul nie musi tego robic.
"""

import ctypes
import logging
import platform
import signal
import subprocess
import threading
from typing import List, Optional

logger = logging.getLogger("lidar_viewer")

# Linie z bridge'a zawierajace ktorykolwiek z tych fragmentow trafiaja na
# poziom WARNING (a nie INFO) - to sa wlasnie te komunikaty, ktore MUSZA byc
# widoczne (global constraint planu: "fail fast and loudly on setup errors").
_WARNING_MARKERS = ("error", "fail", "cannot", "can't", "unable", "warn", "refus")


class BridgeStartError(RuntimeError):
    """Nie udalo sie uruchomic subprocessu bridge'a."""


def _set_pdeathsig() -> None:
    """
    preexec_fn dla Popen: prosi jadro (prctl PR_SET_PDEATHSIG), zeby wyslalo
    SIGTERM do bridge'a, gdy TEN proces (rodzic) zginie - z dowolnego powodu,
    takze SIGKILL/crash calego drzewa src.main, nie tylko normalnym stop().

    Bez tego: gdy proces http_api ginie inaczej niz przez wlasny graceful
    shutdown (ktory wola BridgeManager.stop()), subprocess bridge'a
    (unilidar_publisher_udp) NIE ginie razem z nim - Linux tego nie robi
    automatycznie dla zwyklych dzieci Popen - i zostaje sierota trzymajaca
    /dev/ttyUSB0 na zawsze. Kolejny start() (nowy proces http_api) spawnuje
    drugiego bridge'a, ktory wchodzi w konflikt o ten sam port szeregowy z
    osierocona instancja - obserwowane na zywo jako "IMU dochodzi, Scan nie"
    (mniejsze ramki IMU przechodza mimo przeplotu bajtow z dwoch zrodel,
    wieksze ramki Scan prawie nigdy).

    Dziala tylko na Linuksie (prctl) - na innych platformach no-op, bridge
    i tak jest tam wylacznie do testow.
    """
    if platform.system() != "Linux":
        return
    PR_SET_PDEATHSIG = 1
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM)


class BridgeManager:
    def __init__(
        self,
        executable_path: str,
        serial_port: str,
        dest_ip: str = "127.0.0.1",
        dest_port: int = 12345,
    ):
        self.executable_path = executable_path
        self.serial_port = serial_port
        self.dest_ip = dest_ip
        self.dest_port = dest_port
        # Uzywane WYLACZNIE w testach, zeby podmienic argumenty na
        # nieszkodliwy skrypt zamiast prawdziwej binarki bridge'a.
        # self.serial_port jest wtedy nadal doklejany jako pierwszy
        # argument (w testach niesie flage "-c" dla `python3 -c <script>"),
        # a _extra_args dostarcza reszte (sam skrypt).
        self._extra_args: Optional[List[str]] = None
        self._process: Optional[subprocess.Popen] = None
        self._log_thread: Optional[threading.Thread] = None

    def _reap_if_dead(self) -> None:
        """
        Sprzata po procesie, ktory juz sie zakonczyl (zombie -> None).

        Bez tego `start()` po padzie bridge'a byl cichym no-opem: warunek
        `if self._process is not None` byl nadal prawdziwy dla martwego
        procesu, wiec petla restartow w app.py logowala restarty, ktore
        nigdy sie nie zdarzyly (ten sam PID przed i po "restarcie").
        """
        if self._process is None:
            return
        if self._process.poll() is None:
            return  # zyje
        if self._log_thread is not None:
            self._log_thread.join(timeout=2)
            self._log_thread = None
        if self._process.stdout is not None:
            try:
                self._process.stdout.close()
            except OSError:
                pass
        self._process.wait()  # reap - proces juz wyszedl, nie blokuje
        logger.info("Bridge zakonczyl sie z kodem %s", self._process.returncode)
        self._process = None

    def _drain_output(self, process: subprocess.Popen) -> None:
        """
        Czyta stdout bridge'a linia po linii az do jego konca.

        KONIECZNE: stdout=PIPE bez czytania oznacza, ze dziecko zablokuje sie
        na write() po zapelnieniu bufora potoku systemowego (~64KB), a
        prawdziwy unilidar_publisher_udp drukuje na kazdy sparsowany pakiet.
        Przy okazji kazdy komunikat diagnostyczny bridge'a trafia do logow
        zamiast znikac w nieczytanym potoku.
        """
        stream = process.stdout
        if stream is None:
            return
        try:
            for raw_line in iter(stream.readline, b""):
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                if not line:
                    continue
                lowered = line.lower()
                if any(marker in lowered for marker in _WARNING_MARKERS):
                    logger.warning("[bridge] %s", line)
                else:
                    logger.info("[bridge] %s", line)
        except (ValueError, OSError):
            # stream zamkniety przez stop()/_reap_if_dead w trakcie czytania
            pass

    def start(self) -> None:
        # Uwaga: sprawdzamy poll(), a nie samo `is not None` - martwy proces
        # musi zostac sprzatniety, zeby restart faktycznie wystartowal nowy.
        self._reap_if_dead()
        if self._process is not None:
            return

        args = [self.executable_path]
        if self._extra_args is not None:
            args += [self.serial_port] + self._extra_args
        else:
            args += [self.serial_port, self.dest_ip, str(self.dest_port)]

        try:
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                preexec_fn=_set_pdeathsig if platform.system() == "Linux" else None,
            )
        except (FileNotFoundError, PermissionError) as exc:
            raise BridgeStartError(
                f"Nie znaleziono binarki bridge'a: {self.executable_path}"
            ) from exc

        self._process = process
        self._log_thread = threading.Thread(
            target=self._drain_output,
            args=(process,),
            name="bridge-stdout-drain",
            daemon=True,  # nie blokuje wyjscia z procesu, nawet jesli utknie
        )
        self._log_thread.start()
        logger.info("Bridge wystartowal (pid %d): %s", process.pid, " ".join(args))

    def is_alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def pid(self) -> Optional[int]:
        """PID biezacego procesu bridge'a (albo None) - do diagnostyki/testow."""
        return self._process.pid if self._process is not None else None

    def stop(self) -> None:
        if self._process is None:
            return
        self._process.terminate()
        try:
            # unilidar_publisher_udp.cpp od niedawna obsluguje SIGTERM
            # kontrolowanym zamknieciem: ustawia fizyczny LiDAR w tryb
            # STANDBY (silnik/laser skanujacy off) PRZED wyjsciem, zamiast
            # ginac natychmiast - bez tego LiDAR zostawal w trybie NORMAL
            # (dalej skanujac) mimo zatrzymania bridge'a, bo proces nigdy
            # wczesniej nie mial szansy wyslac tej komendy. Zmierzone na
            # zywym urzadzeniu: ta sciezka trwa zwykle ~1s, ale w jednym
            # przebiegu (SDK zglosilo "Serial port timeout" przy starcie)
            # zajela >5s - poprzedni timeout 5s regularnie wygasal PRZED
            # dotarciem do STANDBY, wymuszajac kill() (SIGKILL, bez szans
            # na cleanup) i cichym niweczeniem calej poprawki. 10s daje
            # realny zapas ponad zmierzony przypadek.
            self._process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()
        if self._log_thread is not None:
            # Proces nie zyje, wiec potok dostaje EOF i watek konczy sie sam;
            # timeout tylko po to, zeby stop() nigdy nie wisial.
            self._log_thread.join(timeout=5)
            self._log_thread = None
        if self._process.stdout is not None:
            try:
                self._process.stdout.close()
            except OSError:
                pass
        self._process = None
