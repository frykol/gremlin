# Standalone UDP LiDAR Viewer — Design Spec

Data: 2026-08-25
Status: zatwierdzony do implementacji (brainstorming ukończony)

## Cel

Samodzielna aplikacja (bez ROS) do odbioru na żywo i wizualizacji danych z
Unitree LiDAR L1 (chmura punktów + IMU), zastępująca dotychczasową sekcję
"Chmura punktów LiDAR" w projekcie `gremlin`. Musi obsługiwać zarówno live
stream, jak i odtwarzanie nagrań (do testów bez podłączonego sprzętu).

## Zakres i migracja (WAŻNE)

To jest **nowa, samodzielna aplikacja**, nie tab wewnątrz istniejącego
dashboardu `gremlin` (`site/`). Zastępuje funkcjonalnie, nie strukturalnie —
własny proces, własny port, własny frontend.

**Do usunięcia z `gremlin` jako część tej pracy** (bo ich funkcję przejmuje
nowa aplikacja):
- `src/hardware/lidar/unitree_l1.py` (parser MAVLink/serial) i jego testy
- `src/workers/lidar_worker.py`, `src/workers/slam_worker.py`
- `src/hardware/lidar/slam.py`, `src/logic/mecanum_odometry.py` (SLAM był
  budowany na starym pipeline'ie punktów; do ponownej oceny później, jeśli
  będzie potrzebny w nowej architekturze — poza zakresem tego spec-a)
- Obsługa `get_lidar_points`/`get_slam_pose` w `command_processor.py`
- `site/public/tabs/lidar.js` i odwołania do niego w `index.html`
- Sekcje `lidar`, `slam`, `drivetrain` w `config.json` (drivetrain zostaje,
  jeśli coś innego z niego korzysta — do sprawdzenia w planie implementacji)

**Zostaje bez zmian:** `src/hardware/lidar/obstacle_reducer.py` (samodzielny
prototyp pod L2, niezależny od tego pipeline'u) — decyzja z wcześniejszej
sesji, poza zakresem tego spec-a.

Usunięcie ma być częścią implementation planu (osobne, jawne kroki), nie
efektem ubocznym dodawania nowego kodu.

## Architektura

```
Unitree L1 --serial--> unilidar_publisher_udp (bridge, C++, z SDK)
                              --UDP-->
Python backend (asyncio, jeden proces):
  bridge_manager  - spawn/pilnowanie subprocess bridge'a
  udp_listener    - odbiór datagramów UDP
  frame_parser    - dekodowanie Scan(102)/IMU(101) wg struct z SDK
  recorder/player - nagrywanie i odtwarzanie surowych ramek UDP
  ws_server       - broadcast binarny do frontendu
  http (static)   - serwuje frontend
                              --WS (binary)-->
Frontend (vanilla JS + Three.js wendorowany lokalnie, zero CDN):
  ws_client, pointcloud (BufferGeometry, live update), viewer (kamera
  orbitalna, wlasna implementacja), imu_panel, metrics_panel
```

Jeden proces Python (`asyncio`) obsługuje subprocess bridge'a, nasłuch UDP,
parsowanie, WS i serwowanie statycznego frontendu. Frontend to pojedyncza
strona HTML/JS, bez frameworka.

## Komponenty

### Backend (`lidar_viewer/backend/`)
- `bridge_manager.py` — `subprocess.Popen` na
  `unilidar_publisher_udp <serial_port> 127.0.0.1 <udp_port>`; restart przy
  padzie, `terminate()` przy zamknięciu aplikacji.
- `udp_listener.py` — `asyncio.DatagramProtocol`, dekoduje nagłówek
  `msgType`(uint32)+`length`(uint32), przekazuje surowy payload dalej.
- `frame_parser.py` — czysta logika, bez zależności sieciowych:
  - IMU (`msgType==101`): `struct.unpack("=dI4f3f3f", payload)` →
    `ImuFrame(stamp, id, quaternion[4] xyzw, angular_velocity[3],
    linear_acceleration[3])`
  - Scan (`msgType==102`): `stamp(d) id(I) validPointsNum(I)` +
    `validPointsNum × struct.unpack("=fffffI", ...)` →
    `ScanFrame(stamp, id, points: list[(x,y,z,intensity,time,ring)])`
  - Testowalna jednostkowo bez sieci/UDP.
- `recorder.py` — dopisuje surowe ramki (nagłówek oryginalny + 8-bajtowy
  znacznik czasu monotonicznego) do pliku, sekwencyjnie, bez zależności od
  ROS.
- `player.py` — czyta plik nagrania, odtwarza z zachowaniem oryginalnych
  odstępów czasowych, karmi tym samym `frame_parser` co live UDP.
- `accumulator.py` — ring buffer punktów (okno czasowe, konfigurowalne,
  domyślnie kilka sekund) — pojedynczy Scan ma do 120 punktów, pełny kształt
  3D wymaga akumulacji wielu Scanów w czasie (potwierdzone wcześniej na
  analogicznym pipeline MAVLink: bez akumulacji chmura wygląda płasko/jak
  cienka wstążka). Filtr zasięgu (odrzuć punkty > próg, konfigurowalny,
  domyślnie 6-10m) stosowany tu, przed wysyłką.
- `ws_server.py` — `websockets`, broadcast:
  - ramka Scan: binarnie, nagłówek (typ, liczba punktów) + `Float32Array`
    (x,y,z,intensity) — może być pełny bufor akumulatora albo tylko delta
    nowych punktów (delta preferowana wydajnościowo, do potwierdzenia przy
    implementacji czy real-time budżet tego wymaga).
  - ramka IMU: binarnie, kwaternion + prędkości kątowe + przyspieszenia.
  - ramka metryk: JSON, rzadka (~1/s) — FPS (Scan/s), opóźnienie
    (`now - stamp`), liczba punktów w oknie.
- `app.py` — CLI: tryb live (domyślny, wymaga `--serial-port`) albo
  `--replay <plik>` (bez bridge'a/UDP, dane z `player.py`). Serwuje frontend
  (statyczne pliki) + WS na jednym porcie.

### Skrypt konwersji (jednorazowy, poza runtime)
- `tools/convert_bag.py` — używa biblioteki `rosbags` (czysty Python, **bez
  instalacji ROS**) do odczytania istniejącego `.bag`, ekstrahuje
  `PointCloud2`/`Imu`, zapisuje w formacie `recorder.py` — uruchamiany raz
  ręcznie, nie jest częścią aplikacji.

### Frontend (`lidar_viewer/frontend/`, statyczne pliki, Three.js wendorowany lokalnie)
- `viewer.js` — scena, kamera orbitalna (własna implementacja sferyczna,
  bez `OrbitControls` z CDN — to była przyczyna awarii w prototypie),
  pętla `requestAnimationFrame`.
- `pointcloud.js` — `THREE.BufferGeometry` z preallokowanymi
  `Float32Array` (pozycja + kolor), update przez `.set()` +
  `needsUpdate=true` (nie przebudowa geometrii co klatkę). Kolor z
  `intensity`, automatyczna normalizacja min/max w oknie danych (nie z
  wysokości — to myliło w prototypie).
- `imu_panel.js` — tekstowy odczyt kwaternionu/prędkości kątowej.
- `metrics_panel.js` — liczba punktów, FPS (mierzony klient-side),
  opóźnienie (z ramki metryk backendu).
- `ws_client.js` — dekoduje binarne ramki wg uzgodnionych nagłówków.

## Przepływ danych

**Live:** bridge (serial→UDP) → `udp_listener` → (opcjonalnie `recorder`
dopisuje surową ramkę) → `frame_parser` → Scan trafia do `accumulator`
(okno czasowe + filtr zasięgu) → `ws_server` broadcastuje do klientów →
`ws_client` dekoduje → `pointcloud.js` aktualizuje geometrię w miejscu →
`viewer.js` renderuje.

**Playback:** identyczne od `frame_parser` w dół; `player.py` zamiast
`udp_listener` dostarcza te same surowe ramki z pliku w oryginalnym tempie.

**Metryki:** liczone w backendzie, wysyłane osobną, rzadką ramką JSON.

## Obsługa błędów

- Bridge nie startuje (zły port szeregowy / już zajęty) → backend loguje
  czytelny błąd i kończy działanie z niezerowym kodem (fail fast, nie cichy
  brak danych — to był realny problem w poprzednim pipeline MAVLink: cisza
  zamiast błędu).
- Bridge pada w trakcie działania → `bridge_manager` próbuje restart z
  limitowaną liczbą prób i logiem; po wyczerpaniu prób aplikacja
  sygnalizuje stan "brak danych" w UI (nie udaje że wszystko działa).
- Uszkodzona/niepełna ramka UDP (np. `length` niezgodny z realnym
  rozmiarem payloadu) → odrzucana z logiem na poziomie debug, nie crashuje
  parsera.
- WS klient się rozłącza → serwer usuwa go z listy broadcastu, nie wpływa
  na innych klientów ani na pipeline danych.
- Plik nagrania nie istnieje / uszkodzony → czytelny błąd przy starcie w
  trybie `--replay`, aplikacja nie startuje w cichym pustym stanie.

## Testowanie

- `frame_parser.py` — testy jednostkowe na syntetycznych bajtach (znane
  struct.pack → oczekiwany `ImuFrame`/`ScanFrame`), analogicznie do testów
  round-trip zrobionych wcześniej dla MAVLink w tej sesji.
- `accumulator.py` — testy okna czasowego i filtra zasięgu na sztucznych
  seriach punktów.
- `recorder.py`/`player.py` — test round-trip: nagraj syntetyczne ramki,
  odtwórz, porównaj z oryginałem (bajt w bajt + zachowane odstępy czasowe
  w granicach tolerancji).
- Integracyjnie: `--replay` na skonwertowanym `.bag` jako weryfikacja
  end-to-end bez potrzeby fizycznego sprzętu — to jest główna ścieżka
  testowa dla frontendu i całego pipeline'u.
- Frontend: manualna weryfikacja w przeglądarce (brak fizycznego sprzętu w
  tym środowisku) — brak automatycznych testów wizualnych w pierwszej
  wersji.

## Poza zakresem (świadomie)

- Kontrola prędkości odtwarzania (pauza/przewijanie) — tylko realtime
  replay w pierwszej wersji.
- SLAM/mapowanie na nowym pipeline — stary SLAM (oparty o MAVLink) zostaje
  usunięty wraz z resztą starego pipeline'u; nowy SLAM to osobna, przyszła
  decyzja.
- Autoryzacja/dostęp zdalny do WS — zakładamy użycie lokalne/zaufana sieć.
