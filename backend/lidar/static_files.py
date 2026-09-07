"""
Serwowanie statycznego frontendu z TEGO SAMEGO portu co WebSocket.

Spec ("Architektura": `http (static) - serwuje frontend`, `app.py` - "Serwuje
frontend (statyczne pliki) + WS na jednym porcie") wymaga jednego portu.
Biblioteka `websockets` (asyncio server) pozwala to zrobic bez drugiego
serwera HTTP: hook `process_request` jest wolany PRZED handshakiem WS i jesli
zwroci `Response`, polaczenie konczy sie zwyklą odpowiedzia HTTP zamiast
upgrade'u do WS.

Dzieki temu `frontend/js/main.js` moze wyliczyc URL WS z `window.location` -
strona i WS sa pod tym samym host:port.
"""

import email.utils
import http
import logging
import mimetypes
import os
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import unquote, urlsplit

from websockets.datastructures import Headers
from websockets.http11 import Response

logger = logging.getLogger("lidar_viewer")

DEFAULT_FRONTEND_DIR = str(
    (Path(__file__).resolve().parent.parent / "frontend").resolve()
)

# mimetypes na niektorych systemach nie zna .js/.mjs albo zwraca
# "text/plain" - przegladarka odmowilaby wtedy wykonania skryptu.
_EXPLICIT_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".html": "text/html",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".wasm": "application/wasm",
}


def _content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _EXPLICIT_TYPES:
        base = _EXPLICIT_TYPES[suffix]
    else:
        base = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if base.startswith("text/") or base in ("application/json", "image/svg+xml"):
        return f"{base}; charset=utf-8"
    return base


def _response(status: http.HTTPStatus, body: bytes, content_type: str) -> Response:
    headers = Headers(
        [
            ("Date", email.utils.formatdate(usegmt=True)),
            ("Connection", "close"),
            ("Content-Length", str(len(body))),
            ("Content-Type", content_type),
        ]
    )
    return Response(status.value, status.phrase, headers, body)


def _error(status: http.HTTPStatus, text: str) -> Response:
    return _response(status, text.encode("utf-8"), "text/plain; charset=utf-8")


def resolve_static_path(root: Path, request_target: str) -> Optional[Path]:
    """
    Mapuje sciezke z zadania HTTP na plik w `root`.

    Zwraca None, jesli sciezka wychodzi poza `root` (path traversal, np.
    `/../../etc/passwd`) albo plik nie istnieje / nie jest zwyklym plikiem.
    """
    raw_path = urlsplit(request_target).path
    relative = unquote(raw_path).lstrip("/")
    if relative in ("", "/"):
        relative = "index.html"
    elif relative.endswith("/"):
        relative = relative + "index.html"

    # Odrzuc od razu sciezki absolutne i wszystko, co po normalizacji
    # wyszlo by poza katalog frontendu.
    if os.path.isabs(relative) or "\x00" in relative:
        return None

    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def make_static_process_request(frontend_dir: str) -> Callable:
    """
    Buduje hook `process_request` dla `websockets.serve(...)`.

    Zwraca None dla zadan z naglowkiem `Upgrade: websocket` (wtedy websockets
    normalnie robi handshake), a dla zwyklego HTTP GET odpowiada plikiem
    z `frontend_dir`. (Inne metody niz GET odrzuca sama biblioteka websockets
    juz na etapie parsowania zadania - patrz http11.Request.parse.)
    """
    root = Path(frontend_dir).resolve()
    if not root.is_dir():
        # Fail fast and loudly (global constraint planu) - cicho serwowany
        # 404 na kazdy plik wygladalby jak "aplikacja dziala, tylko pusta".
        raise FileNotFoundError(f"Katalog frontendu nie istnieje: {root}")

    def process_request(connection, request):
        upgrade = request.headers.get("Upgrade")
        if upgrade is not None and upgrade.lower() == "websocket":
            return None  # normalny handshake WS

        path = resolve_static_path(root, request.path)
        if path is None:
            logger.debug("HTTP 404: %s", request.path)
            return _error(http.HTTPStatus.NOT_FOUND, "404 Not Found\n")

        try:
            body = path.read_bytes()
        except OSError as exc:
            logger.warning("Nie mozna odczytac %s: %s", path, exc)
            return _error(
                http.HTTPStatus.INTERNAL_SERVER_ERROR, "500 Internal Server Error\n"
            )

        return _response(http.HTTPStatus.OK, body, _content_type(path))

    return process_request
