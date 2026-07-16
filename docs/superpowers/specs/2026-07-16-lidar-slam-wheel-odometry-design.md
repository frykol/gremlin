# Lidar SLAM z odometrią kołową — design

## Kontekst

`lidar_slam.py` (robot_ws) robi dziś scan-to-map ICP bez żadnego źródła ruchu — initial guess dla każdej nowej ramki to założenie "brak ruchu" względem ostatniej pozy. Przy realnym ruchu robota to założenie jest złe, a ICP bez dobrego punktu startowego łatwo trafia w błędne lokalne minimum (obserwowane w testach jako "fajerwerk" — błędy pozycji kumulujące się między klatkami). Obecne zabezpieczenia (`--min-fitness`, `--max-speed`) łagodzą objawy, ale nie usuwają przyczyny.

W repo (`ros2_ws/src/motor_driver/motor_driver/odometry.py`) istnieje gotowa, czysto pythonowa funkcja `integrate_odometry(x, y, theta, vx, vy, wz, dt)` — dead-reckoning z prędkości ciała robota. Jest dziś osierocona: żywy stos sterowania (`gremlin/src/robot_controller.py` + `i2cPWM`) operuje wyłącznie na surowym procencie PWM per kanał, bez warstwy `vx/vy/wz`.

Robot ma napęd mecanum (4 koła, pełny ruch we wszystkich kierunkach — zgodnie z założeniem `vx+vy` w `integrate_odometry`).

## Cel

Dać ICP w `lidar_slam.py` sensowny initial guess z prędkości kół zamiast zgadywania "brak ruchu", bez wprowadzania loop closure (świadomie poza zakresem — nie mamy jeszcze danych z realnego ruchu robota, żeby ocenić, czy jest potrzebne).

## Architektura

Dwa niezależne procesy, komunikujące się przez lekki plik stanu (nie gniazdo — prościej, mniej punktów awarii):

1. **`robot_controller`** (istniejący proces asyncio) — dodatek: co ~50-100ms zapisuje aktualnie zadane prędkości/kierunki 4 kół do pliku stanu (np. `/tmp/wheel_state.json`), ze znacznikiem czasu monotonicznego.
2. **`lidar_slam.py`** (istniejący, standalone) — nowy moduł `wheel_odometry_reader.py` odczytuje ten plik na starcie każdej ramki ICP, liczy `(vx, vy, wz)` modelem kinematyki mecanum, całkuje przez `integrate_odometry()` względem poprzedniego odczytu, i podaje wynik jako initial guess do ICP zamiast dzisiejszej identity transform.

## Komponenty

- **`wheel_kinematics.py`** (nowy, robot_ws) — czysta matematyka: prędkości 4 kół (rad/s, ze znakiem) → `(vx, vy, wz)` standardowym modelem kinematyki mecanum. Wymaga stałych geometrii (promień koła, rozstaw osi) — do ustalenia przed planem implementacji (nie są dziś nigdzie w kodzie).
- **Dodatek w `robot_controller`/`command_processor`** — zapis stanu kół (prędkość+kierunek per koło, timestamp monotoniczny) do pliku, cyklicznie.
- **`wheel_odometry_reader.py`** (nowy, robot_ws) — odczyt pliku stanu, śledzenie delt czasu, wywołanie `integrate_odometry()` → kumulatywna delta pozycji od ostatniego odczytu.
- **`lidar_slam.py` (zmiana)** — `add_frame()` przyjmuje opcjonalny initial guess z odometrii; nowy CLI arg `--odom-state-file`; jeśli plik nieobecny/nieaktualny → fallback do dzisiejszego zero-motion, żeby SLAM działał samodzielnie nawet bez `robot_controller`.
- **Guard `--max-speed` (zmiana logiki)** — zamiast porównania do sztywnej stałej, porównuje wynik ICP z przewidywaniem z odometrii; zbyt duża rozbieżność → odrzucenie ramki (mocniejszy sanity check niż dziś, bo wykrywa też sytuacje gdy ICP "zjechał" mimo wiarygodnej prędkości).

## Przepływ danych

`robot_controller` zapisuje stan kół co ~50-100ms → `lidar_slam` na starcie każdego okna czasowego (`--frame-window`, domyślnie 0.2s) odczytuje najnowszy wpis, całkuje `vx,vy,wz` względem poprzedniego odczytu → delta pozycji jako initial guess dla ICP → ICP dopasowuje względem mapy → guard porównuje wynik z przewidywaniem odometrii → akceptuj/odrzuć (jak dziś, `min-fitness` zostaje jako dodatkowy warunek).

## Obsługa błędów

- Plik stanu nieobecny lub starszy niż 2× `frame-window` → brak danych o ruchu, fallback do zero-motion (dzisiejsze zachowanie); log ostrzeżenia raz, nie spamujemy przy każdej ramce.
- Różnice zegarów między procesami → licznik czasu monotonicznego zapisywany w pliku stanu, nigdy porównanie zegarów ściennych między procesami.
- Zdegenerowana geometria (np. promień koła = 0) → walidacja stałych kinematyki przy starcie `lidar_slam`, czytelny błąd zamiast cichego dzielenia przez zero.

## Testowanie

- **`wheel_kinematics.py`** — testy jednostkowe: znane prędkości 4 kół → oczekiwane `(vx, vy, wz)`. Czysta matematyka, bez sprzętu.
- **Integracja `lidar_slam` + odometria** — syntetyczny test: znana delta odometrii + przesunięta kopia chmury punktów → weryfikacja, że `add_frame()` zbiega do właściwej pozycji, i że guard odrzuca celowo błędny wynik ICP.
- **Test na sprzęcie** — przejazd robota po znanej trasie (prosta linia o zmierzonej długości), porównanie estymowanej trajektorii z rzeczywistą. Jedyny test weryfikujący, czy `wheel_state.json` faktycznie nadąża i czy stałe geometrii są poprawne.

## Poza zakresem (świadomie)

- Loop closure / pose graph — brak jeszcze danych z realnego ruchu robota, żeby ocenić potrzebę.
- Fuzja EKF odometrii z ICP (rozważana jako alternatywa C w brainstormingu) — bardziej rygorystyczna statystycznie, ale znacząco więcej pracy; naturalny następny krok, jeśli podejście z tego dokumentu okaże się niewystarczające po testach na jeżdżącym robocie.
- Kalibracja rzeczywistej geometrii koła/rozstawu — stałe będą potrzebne jako dane wejściowe do planu implementacji, ich pomiar/ustalenie to osobny krok.
