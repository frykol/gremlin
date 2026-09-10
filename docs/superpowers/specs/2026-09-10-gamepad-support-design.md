# Wsparcie dla kontrolera USB (gamepad) — Design Spec

Data: 2026-09-10
Status: zatwierdzony do implementacji (brainstorming ukończony)

## Cel

Automatyczne wykrywanie podłączonego przez USB gamepada (dowolny pad HID,
np. Xbox/PS), zmapowanie jego surowych przycisków/osi na nazwane kontrolki
oraz przesyłanie na żywo (event-driven, przy każdej zmianie stanu) informacji
o jego stanie do trzeciej aplikacji podłączonej po WiFi — przez nowy,
dedykowany kanał WebSocket, niezależny od istniejącego `WsServer` używanego
przez `site`.

Poza zakresem tej pracy: sterowanie robotem gamepadem (tłumaczenie stanu
pada na komendy jazdy). To tylko wykrycie + mapowanie + broadcast stanu.

## Architektura

Nowy moduł sprzętowy `src/hardware/gamepad/` zbudowany dokładnie wg
istniejącego wzorca hot-plug używanego dla lidaru/kamery/mikrofonu
(`DeviceSlot` + `DeviceMonitor` + `factory.py` + dummy), plus drugi,
niezależny obiekt `WsServer` (klasa już istnieje i jest generyczna — patrz
`src/dev_connection/ws_server.py`) nasłuchujący na osobnym porcie dla
trzeciej aplikacji, zasilany przez nowy `GamepadWorker`.

```
USB gamepad --evdev--> GamepadInterface (real/dummy)
                              |
                         DeviceSlot + DeviceMonitor (hot-swap)
                              |
                        GamepadWorker (poll + diff)
                          /          \
                RobotState.gamepad_state    WsServer #2 (nowy port)
                                                      |
                                            trzecia aplikacja (WiFi)
```

## Komponenty

### 1. `requirements.txt`
Dodanie zależności `evdev` (odczyt `/dev/input/eventX` na Linuksie, działa
z dowolnym gamepadem HID bez własnych sterowników).

### 2. `src/hardware/gamepad/interface.py`
ABC `GamepadInterface` z metodami `start()`, `stop()`, `is_healthy()`,
`get_state() -> GamepadState`, analogicznie do `MicArrayInterface`.

`GamepadState` (dataclass): `buttons: dict[str, bool]`, `axes: dict[str,
float]` (znormalizowane -1..1) — klucze to **nazwy z mapowania w
config.json**, nie surowe kody evdev.

### 3. `src/hardware/gamepad/gamepad.py` (real)
- `start()`: skanuje `evdev.list_devices()`, wybiera pierwsze urządzenie
  z możliwościami joysticka (`EV_ABS` + `EV_KEY`), otwiera przez
  `InputDevice`.
- Odczyt zdarzeń w tle (asyncio task czytający `async_read_loop()`
  z `evdev`), aktualizujący wewnętrzny stan raw (evdev code -> wartość).
- Tłumaczenie raw evdev code -> nazwana kontrolka wg
  `config["gamepad"]["mapping"]` (np. `"BTN_SOUTH": "a"`,
  `"ABS_X": "left_stick_x"`). Kody spoza mapowania są ignorowane.
- `is_healthy()`: sprawdza czy fd urządzenia jest wciąż czytelny (łapie
  `OSError`/`ENODEV` przy odłączeniu USB).
- `get_state()`: zwraca kopię (snapshot) aktualnego nazwanego stanu.

### 4. `src/hardware/gamepad/dummy_gamepad.py`
`FakeGamepad(GamepadInterface)`, `IS_DUMMY = True`, `is_healthy()` zawsze
`True`, `get_state()` zwraca stan neutralny (wszystkie buttony `False`,
wszystkie osie `0.0`) zbudowany z tego samego mapowania z configu — żeby
nazwy pól zawsze były spójne z rzeczywistym padem.

### 5. `src/hardware/gamepad/factory.py`
`create_gamepad(config)`, identyczny kształt jak `create_mic_array`:
- `config["gamepad"]["is_dummy"]` → krótkie spięcie do samego dummy,
  bez monitora.
- W przeciwnym razie: próba `_build_real(config)`, fallback do
  `_build_dummy(config)` przy wyjątku (log przez `log_device_status`).
- Wynik owinięty w `DeviceSlot`, doczepiony `DeviceMonitor(build_real,
  build_dummy, poll_interval=config.get("device_health_check_interval",
  5.0))`, uruchomiony przez `start_device_monitor`, task zapisany na
  `slot.monitor_task`.

### 6. `config.json`
Nowa sekcja `"gamepad"`:
```json
"gamepad": {
  "is_dummy": false,
  "mapping": {
    "BTN_SOUTH": "a", "BTN_EAST": "b", "BTN_WEST": "x", "BTN_NORTH": "y",
    "BTN_TL": "bumper_l", "BTN_TR": "bumper_r",
    "BTN_START": "start", "BTN_SELECT": "back",
    "ABS_X": "left_stick_x", "ABS_Y": "left_stick_y",
    "ABS_RX": "right_stick_x", "ABS_RY": "right_stick_y",
    "ABS_Z": "trigger_l", "ABS_RZ": "trigger_r"
  }
}
```
Nowa sekcja `"gamepad_ws_server"`: `{"host": "...", "port": 8768}` (osobny
port od istniejącego `ws_server` używanego przez site, np. 8768).

### 7. `src/robot_state.py`
Nowe pole `gamepad_state: GamepadState | None = None`.

### 8. `src/workers/gamepad_worker.py`
`GamepadWorker(gamepad: DeviceSlot, state: RobotState, gamepad_ws:
WsServer, poll_interval: float = 0.005)`:
- Pętla w konwencji istniejących workerów (ten sam try/except na
  `resolve(self.gamepad).get_state()` co w camera/lidar/mic worker, żeby
  pojedynczy błąd odczytu nie ubijał pętli na stałe).
- Zapisuje aktualny stan do `state.gamepad_state`.
- Trzyma poprzednio **wysłany** stan i porównuje go z bieżącym; wysyła
  `await gamepad_ws.send(json.dumps({"type": "gamepad_state", "buttons":
  {...}, "axes": {...}}))` tylko gdy coś się faktycznie zmieniło
  (event-driven push, zgodnie z wymaganiem).

### 9. `src/main.py`
- Drugi `WsServer(gamepad_host, gamepad_port, gamepad_instruction_tab)`
  (kolejka na wejście nieużywana — kanał jest tylko wyjściowy), własny
  task `connect()`.
- `create_gamepad(config)` → slot, `GamepadWorker(...)` uruchamiany obok
  pozostałych workerów.
- Dodanie zamknięcia nowego `WsServer` i zatrzymania workera do sekwencji
  shutdown (tam gdzie dziś jest `ws.close()`/`stop_program_manager()`).

## Obsługa błędów

- Brak podłączonego pada przy starcie → `create_gamepad` łapie wyjątek z
  `_build_real` (np. brak urządzenia z capability joysticka) i wystawia
  dummy; `DeviceMonitor` będzie co `device_health_check_interval` sekund
  próbował podłączyć prawdziwy pad (ten sam mechanizm co dziś dla
  lidaru/mikrofonu — hot-plug bez restartu usługi).
- Odłączenie pada w trakcie działania → `is_healthy()` zwróci `False` (fd
  nieczytelny), `DeviceMonitor` podmienia slot na dummy.
- Błąd pojedynczego odczytu w `GamepadWorker.run()` → złapany, zalogowany,
  pętla kontynuuje (ten sam wzorzec co
  `tests/test_worker_read_error_resilience.py`).
- Trzecia aplikacja nieaktywna (brak połączenia z nowym `WsServer`) →
  `WsServer.send()` już dziś obsługuje ten przypadek (`if self._connection
  is None: print(...); return`), więc `GamepadWorker` nie musi nic robić
  specjalnego.

## Testowanie

- `tests/test_gamepad_factory.py` — analogiczny do istniejących testów
  fabryk (`test_camera_factory.py`): `is_dummy=True` → dummy bez monitora;
  brak urządzenia → fallback do dummy.
- `tests/test_dummy_hot_swap_started.py` (rozszerzenie) lub nowy analogiczny
  test — dummy gamepad startuje poprawnie i `DeviceMonitor` próbuje
  odzyskać prawdziwe urządzenie.
- `tests/test_gamepad_worker.py` — wzorzec z
  `test_worker_read_error_resilience.py`: flaky `get_state()` rzucający
  raz, worker przeżywa i wraca do normalnego działania; osobny test
  sprawdzający, że `gamepad_ws.send()` wywoływane jest tylko przy zmianie
  stanu (nie przy każdej iteracji pętli).
- `tests/test_gamepad_mapping.py` — jednostkowy test tłumaczenia surowych
  kodów evdev na nazwane pola wg mapowania z configu (bez realnego
  urządzenia — mockowany strumień eventów).

## Poza zakresem (YAGNI)

- Autoryzacja / wielu klientów na nowym WebSocket — jeden klient, bez
  auth, tak jak dzisiejszy `WsServer` (sieć WiFi lokalna, zaufana).
- Tłumaczenie stanu gamepada na komendy sterowania robotem — osobna,
  przyszła praca.
- Konfigurowalny wybór *którego* z kilku podłączonych padów użyć, jeśli
  jest więcej niż jeden — na start bierzemy pierwszy pasujący z
  `evdev.list_devices()`.
