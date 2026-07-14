# Podsumowanie repozytorium "gremlin" (branch ros2)

## Cel projektu
Gremlin to projekt robota (prawdopodobnie na Raspberry Pi), łączący klasyczny kod Python sterujący sprzętem z workspace'em ROS2. `config.json` wskazuje na sprzęt: GPIO (gpiod), silniki (I2C, R_EN/L_EN), kamerę stereo OAK-D (depthai), mikrofon ReSpeaker 4 Mic Array, czytnik kart SD, przycisk reset oraz strumieniowanie obrazu przez UDP/WebSocket do hosta 192.168.1.162. Zależności (`requirements.txt`): numpy, opencv-python, gpiod, smbus2, websockets, depthai<3, sounddevice. `README.md` zawiera jedynie tytuł "gremlin" (brak opisu).

## Struktura katalogów
- **`src/`** – główny kod aplikacji (Python, nie-ROS): `main.py`, `robot_controller.py`, `robot_state.py`, `config.py`, `program_manager.py`, `default.py`, `reset_daemon.py`; moduły `hardware/` (gpio, i2c, oak_d, respeaker, sd_card, lidar – z wzorcem interface/factory/dummy dla łatwego mockowania sprzętu), `logic/robot_logic.py`, `services/` (camera_streamer, audio_streamer, command_processor), `workers/` (camera_worker, mic_worker), `dev_connection/` (client/server, UDP frame sender, pipe_client – komunikacja z zewnętrznym interfejsem).
- **`custom_basic_structure/`** – niemal identyczna, uproszczona kopia struktury `src/` (szablon/przykład bazowej architektury, prawdopodobnie do nauki lub jako wzorzec startowy).
- **`interface/`** – GUI/panel diagnostyczny (prawdopodobnie PyQt/Tkinter): `app.py`, `GPIO_view.py`, `I2C_view.py`, `Camera_view.py`, `Mic_view.py`.
- **`deploy/`** – plik `reset-daemon.service` (usługa systemd do obsługi przycisku resetu).
- **`robot_ws/ros2_ws/`** – workspace ROS2 (colcon), pakiety w `src/`: `motor_driver`, `gesture_node`, `voice_node` (zawiera podkatalog `llama/` z integracją Ollama/Bielik – lokalny LLM głosowy), `robot_bringup` (z jedynym launch file `launch/robot.launch.py`) oraz zewnętrzny SDK `unilidar_sdk` (LIDAR Unitree, z własnym repo git w środku). Zawiera też skompilowane `build/`, `install/`, logi budowania (`log/`) oraz mapy (`maps/`).
- **`tests/`** – dwa testy: `test_websocket_config.py`, `test_camera_streamer.py`.

## Czy to projekt robotyczny?
Tak – ROS2 (workspace colcon w `robot_ws/ros2_ws`) obsługuje sterowanie silnikami (`motor_driver`), rozpoznawanie gestów (`gesture_node`), głos/LLM (`voice_node` z Ollama), LIDAR (Unitree) oraz uruchamianie całości przez `robot_bringup`/`robot.launch.py`. Równolegle istnieje osobna (nie-ROS) warstwa Python w `src/` do obsługi kamery, mikrofonu, GPIO i strumieniowania – wygląda na hybrydową architekturę, gdzie `src/` może być starszą/równoległą wersją funkcjonalności migrowanej do ROS2.

## Stan repozytorium
- Branch `ros2`, aktualny względem `origin/ros2` (brak rozbieżności z remote).
- Niezacommitowane zmiany (modified): `config.json`, `robot_ws/.../voice_node.py`, `sim.log`, `src/default.py`, `src/dev_connection/client_factory.py`, `src/main.py`.
- Untracked: `.cache/`, `.vscode/`, `robot_ws/.../voice_node/llama/ollama-python/`, `src/dev_connection/pipe_client.py`, `src/program_manager.py`.
- Ostatnie commity: "super duper changes", "ros" (dodanie ROS2), wcześniej poprawki interfejsu, mikrofonu, I2C, GPIO – historia pokazuje stopniowy rozwój od interfejsu diagnostycznego do integracji ROS2.
- Istnieją też branche `main`, `interface`, `oakd` – sugeruje to development feature-branch'owy scalany do main/ros2.

## Uwagi
- W `sim.log` widoczny błąd: `OSError: [Errno 101] Network is unreachable` przy próbie wysyłki klatki kamery przez UDP (`udp_frame_sender.py`) – prawdopodobnie brak połączenia z hostem docelowym (192.168.1.162) podczas testu symulacyjnego. Poza tym log pokazuje normalne starty/zatrzymania modułów dummy (SD card, OAK-D, ReSpeaker) w trybie deweloperskim.
- Duża liczba niezacommitowanych zmian i nowych plików (w tym `program_manager.py`, `pipe_client.py`) sugeruje aktywną, niedokończoną pracę nad refaktoryzacją komunikacji (dev_connection) i integracją Ollama w `voice_node`.
- `.gitignore` jest minimalny (`.venv/`, `__pycache__/`, `*.pyc`) – nie ignoruje katalogów budowania ROS2 (`build/`, `install/`, `log/`) ani `sim.log`/`.vscode`, mimo że te ostatnie są w repo/roboczo śledzone lub untracked – warto rozważyć rozszerzenie.
- `.vscode/extensions.json` rekomenduje jedynie rozszerzenie `anthropic.claude-code`.
- Obecność zewnętrznego repozytorium git wewnątrz `unilidar_sdk` (zagnieżdżony `.git`) może wymagać ustawienia jako submodule, by uniknąć problemów przy commitowaniu.
