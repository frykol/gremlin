# Custom program dla robota

Ten katalog to szkielet do własnego programowania robota, kopiowany na kartę SD wkładaną do czytnika HW-125.

## Zawartość

- `custom.py` — Twój program. Musi zawierać `async def init(config)` oraz `async def loop(config)`.
  Robot przy starcie sprawdza czy ten plik istnieje na karcie — jeśli tak, używa go zamiast domyślnej logiki.
- `src/` — kopia frameworka robota (sterowniki GPIO/I2C, kamera, mikrofon, karta SD, połączenie WS,
  `RobotController` itd.). `custom.py` korzysta z tego przez zwykłe importy, np.
  `from src.hardware.gpio.gpio_controller import GPIOController`. Nie trzeba niczego doinstalowywać —
  wszystko czego potrzebujesz jest tutaj, na karcie.
- `config.json` — przykładowa kopia konfiguracji robota, czysto poglądowa (pokazuje jakie pola trafiają
  do `config` przekazywanego do `init`/`loop`). Robot i tak wczytuje swój własny `config.json` z dysku
  systemowego, ten plik na karcie nie jest przez niego czytany.

## Jak zacząć

1. Skopiuj cały ten katalog na kartę SD (pliki muszą być w katalogu głównym karty, nie w podfolderze).
2. Edytuj `custom.py` — `init(config)` wywoływane jest raz na starcie, `loop(config)` uruchamia właściwą
   pracę robota (domyślnie po prostu odpala `RobotController.run()`).
3. Włóż kartę do czytnika i uruchom robota — jeśli `custom.py` jest na karcie, zostanie użyty automatycznie.

## Wyłączanie programów custom

Pole `is_custom` w głównym `config.json` robota (na dysku systemowym, nie na karcie) pozwala całkowicie
wyłączyć wczytywanie `custom.py` z karty — gdy `is_custom: false`, robot zawsze uruchamia `default.py`,
nawet jeśli na karcie leży `custom.py`.
