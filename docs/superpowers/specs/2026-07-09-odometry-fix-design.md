# Naprawa odometrii (motor_driver) — design

## Problem

`motor_driver.py` publikuje `/odom` i TF `odom→base_link`, ale pozycja
(`_x`, `_y`, `_theta`) nigdy nie jest aktualizowana — robot zawsze
raportuje pozycję (0,0,0). W efekcie `slam_toolbox` nie ma żadnego
motion prior między skanami lidaru i opiera się wyłącznie na
dopasowaniu skanów, co powoduje dryf/błędy mapy, zwłaszcza przy
obrotach i szybkim ruchu.

Robot nie ma fizycznych enkoderów kół — sterowanie silnikami BTS7960
jest open-loop (PWM przez PCA9685, bez sprzężenia zwrotnego).

## Zakres

Tylko `robot_ws/ros2_ws/src/motor_driver/motor_driver/motor_driver.py`.
Offsety TF lidaru/kamery (`base_to_laser_tf` w `robot.launch.py`)
pozostają jako istniejące TODO — poza zakresem tej zmiany.

## Rozwiązanie: open-loop (kinematyczna) odometria

Ponieważ nie ma enkoderów, jedyne dostępne źródło ruchu to zadana
komenda `/cmd_vel`. Odometria będzie dead-reckoningiem: integracją
kinematyki mecanum w czasie na podstawie ostatniej znanej komendy
(tej samej, która już steruje kołami w `_tick()`).

### 1. Integracja pozycji w `_tick()`

Dla każdego wywołania timera (50 Hz):
- policzyć `dt` od poprzedniego wywołania (`time.monotonic()`),
- wziąć `vx, vy, wz` z aktualnie używanej komendy `cmd` (już obliczanej
  w `_tick()` przed `mecanum_inverse_kinematics`),
- zintegrować przemieszczenie w ramce robota i obrócić o `self._theta`
  przed dodaniem do `self._x`, `self._y` (standardowa integracja
  różniczkowa dla ramki 2D):
  ```
  dx = (vx * cos(theta) - vy * sin(theta)) * dt
  dy = (vx * sin(theta) + vy * cos(theta)) * dt
  dtheta = wz * dt
  ```
- zaktualizować `self._x += dx`, `self._y += dy`,
  `self._theta = wrap_to_pi(self._theta + dtheta)`.

### 2. `_publish_odom()`

- Kwaternion z `self._theta` (rotacja wokół Z): `qz = sin(theta/2)`,
  `qw = cos(theta/2)` — zamiast obecnego stałego `z=0, w=1`.
- Uzupełnić `twist.linear.x/y` i `twist.angular.z` bieżącymi `vx, vy,
  wz` (przydatne dla slam_toolbox/Nav2 do estymacji prędkości).
- Dodać macierze kowariancji `pose.covariance` i `twist.covariance`
  (6x6, spłaszczone do 36 elementów) z umiarkowanie wysokimi
  wartościami na przekątnej dla x, y, yaw (oraz odpowiadające im
  prędkości), sygnalizując slam_toolbox, że to słabe źródło pozycji
  względem realnego czujnika — np. rząd wielkości 0.05–0.1 dla
  wariancji liniowej i 0.1–0.2 dla kątowej (do dostrojenia
  empirycznie, ale wystarczające jako "nieidealne, ale użyteczne").
- TF `odom→base_link` używa tego samego kwaternionu i pozycji.

### 3. Brak zmian poza `motor_driver.py`

`slam_toolbox.yaml` już poprawnie oczekuje `odom_frame: odom`,
`base_frame: base_link` — nie wymaga zmian.

## Ograniczenia (świadomie akceptowane)

- To wciąż dead-reckoning z komend, nie z rzeczywistego ruchu kół —
  poślizg kół (typowy dla mecanum) nie będzie wykryty i odometria
  będzie się rozjeżdżać z rzeczywistością w czasie. To i tak
  drastyczna poprawa względem stałego (0,0,0).
- Prawdziwe enkodery to osobne zadanie sprzętowe/programowe na
  przyszłość — nie w zakresie tej zmiany.
- Offsety TF lidaru/kamery pozostają przybliżone (TODO w
  `robot.launch.py`) do zmierzenia gdy robot będzie fizycznie
  dostępny.

## Testowanie

Brak fizycznego dostępu do robota w tej sesji — weryfikacja przez:
- `colcon build` dla pakietu `motor_driver` (sprawdzenie składni/importów),
- ręczny przegląd logiki integracji (jednostki, znaki, wrap kąta),
- ewentualny mini-test jednostkowy funkcji integrującej pozycję
  (czysta funkcja, bez zależności od ROS), jeśli uzasadnione.
