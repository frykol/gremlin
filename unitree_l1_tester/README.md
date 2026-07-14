# Tester Unitree 4D LiDAR L1 na Raspberry Pi OS

Projekt korzysta z oficjalnego repozytorium `unitreerobotics/unilidar_sdk` dla modelu **L1**. Nie jest to wersja dla L2 — L1 ma inne SDK i domyślny UART **2 000 000 b/s**.

## Co potrafi

- sprawdza, czy port szeregowy można otworzyć;
- pokazuje liczbę chmur i punktów na sekundę;
- ocenia, czy LiDAR aktualnie wykrywa punkty;
- pokazuje minimalny, średni i maksymalny dystans;
- pokazuje najbliższy punkt XYZ i intensywność odbicia;
- liczy dane IMU;
- przełącza `NORMAL` / `STANDBY`;
- wykonuje automatyczny test: pomiar → czuwanie → wznowienie;
- resetuje LiDAR;
- steruje pierścieniem LED;
- zapisuje ostatnią chmurę punktów do CSV.

## Wymagania

- Raspberry Pi z **64-bitowym Raspberry Pi OS** (`uname -m` powinno zwrócić `aarch64`);
- oryginalny adapter Unitree albo prawidłowy konwerter UART;
- osobne zasilanie L1 **12 V** — nie zasilaj LiDAR-u z pinu 5 V Raspberry Pi;
- użytkownik należący do grupy `dialout`.

## Instalacja

```bash
unzip unitree_l1_tester.zip
cd unitree_l1_tester
chmod +x install.sh run.sh
./install.sh
```

Po pierwszym dodaniu do `dialout` wyloguj się i zaloguj ponownie albo wykonaj:

```bash
newgrp dialout
```

## Znalezienie portu

```bash
ls -l /dev/serial/by-id/ 2>/dev/null
ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
```

Najczęściej będzie to `/dev/ttyUSB0`.

## Uruchomienie

Automatyczne wykrycie pierwszego portu:

```bash
./run.sh
```

Konkretny port:

```bash
./run.sh /dev/ttyUSB0
```

Bez skryptu pomocniczego:

```bash
~/unilidar_sdk/unitree_lidar_sdk/bin/lidar_l1_tester /dev/ttyUSB0
```

Pełne parametry:

```bash
~/unilidar_sdk/unitree_lidar_sdk/bin/lidar_l1_tester \
  /dev/ttyUSB0 2000000 0.05 30 18
```

Kolejność:

```text
port  baudrate  range_min  range_max  cloud_scan_num
```

## Automatyczny test

```bash
./run.sh /dev/ttyUSB0 --autotest
```

Test trwa około 15 sekund:

1. `NORMAL` — sprawdza, czy powstają chmury i punkty.
2. `STANDBY` — sprawdza, czy chmury przestają przychodzić, a IMU nadal działa.
3. `NORMAL` — sprawdza, czy pomiar rusza ponownie.

Po teście program wypisze wynik `PASS` albo `FAIL` i zakończy działanie.

## Komendy interaktywne

```text
start / s            tryb NORMAL
stop / x             tryb STANDBY
cycle / c            STANDBY na 3 sekundy i powrót do NORMAL
autotest / t         pełny automatyczny test
reset / r            reset LiDAR-u
info / i             firmware, SDK, zabrudzenie i opóźnienie
status               natychmiastowy raport
points [N]           pokazanie pierwszych N punktów
imu                   ostatnie dane IMU
snapshot [plik.csv]  zapis ostatniej chmury do CSV
led off               wyłączenie pierścienia LED
led on                włączenie całego pierścienia LED
led slow              wolny obrót wzoru
led fast              szybki obrót wzoru
led reverse           obrót wzoru wstecz
led breath            efekt oddychania
clear                 zerowanie statystyk
quit / q              wyjście
```

## NORMAL, STANDBY i prawdziwe odcięcie zasilania

`stop`/`STANDBY` nie odcina fizycznie przewodu 12 V. Zatrzymuje oba silniki i pomiar punktów, wyłącza LED, zmniejsza pobór mocy i pozostawia transmisję IMU.

Pełne wyłączenie i włączenie zasilania wymaga przekaźnika albo odpowiedniego układu MOSFET po stronie 12 V. Nie podłączaj obciążenia LiDAR-u bezpośrednio do GPIO Raspberry Pi.

## Gdy port istnieje, ale brak punktów

```bash
sudo lsof /dev/ttyUSB0
id
ls -l /dev/ttyUSB0
```

Sprawdź również:

- czy zasilacz L1 ma prawidłowe 12 V;
- czy przewód danych jest podłączony do adaptera Unitree;
- czy program używa 2 000 000 b/s;
- czy LiDAR nie pozostaje mechanicznie zablokowany;
- czy wybrano właściwy port;
- czy żaden inny program nie korzysta z portu.

Możesz podejrzeć komunikaty jądra:

```bash
dmesg --follow
```

## Plik CSV

W czasie działania wpisz:

```text
snapshot test.csv
```

Plik zawiera:

```text
cloud_stamp, cloud_id, x, y, z, distance, intensity, relative_time, ring
```
