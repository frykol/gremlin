# backend_old_UNUSED - NIEUZYWANY duplikat

Te pliki to STARA, martwa kopia backendu LiDAR. Zywy kod to `backend/lidar/`.

Potwierdzenie, ze byly martwe w chwili przeniesienia (2026-09-02):
- `src/main.py:151` uruchamia `backend.lidar.http_api`, nie `backend.http_api`
- wszystkie testy importuja `backend.lidar.*`
- zaden plik .py/.js/.json w projekcie nie importowal `backend.app`
  ani `backend.ws_server`

Kopia rozjechala sie z zywym kodem i NIE zawiera poprawek, m.in.:
- `ws_server.py` (148 roznych linii) - ma nienaprawiony head-of-line
  blocking w broadcast (jeden wolny klient scinal pipeline 20Hz -> 2Hz)
- `app.py` (209 roznych linii) - brak detekcji przeszkod, kalibracji
  plaszczyzny podlogi, scorera anomalii i warstwy trwalosci klastrow
- `http_api.py` (197 roznych linii)

Nie przywracac tych plikow do `backend/`. Do usuniecia, gdy tylko
potwierdzisz, ze nic ich nie potrzebuje.
