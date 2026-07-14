#!/usr/bin/env bash
# Wykrywa nowo podłączone urządzenie szeregowe (np. Unitree L2 LiDAR).
# Użycie: podłącz lidar (kabel USB + zasilanie), a potem uruchom ten skrypt.
# Pokazuje wszystkie urządzenia szeregowe, ich vendor/product ID i ostatnie
# wpisy dmesg dotyczące USB, żeby ustalić który /dev/ttyUSBx / ttyACMx
# odpowiada lidarowi.

set -euo pipefail

echo "== /dev/serial/by-id (stabilne symlinki, jeśli dostępne) =="
ls -la /dev/serial/by-id/ 2>/dev/null || echo "(brak /dev/serial/by-id)"

echo
echo "== Urządzenia ttyUSB* / ttyACM* =="
found=0
for dev in /dev/ttyUSB* /dev/ttyACM*; do
    [ -e "$dev" ] || continue
    found=1
    name=$(basename "$dev")
    sys_path="/sys/class/tty/${name}/device"
    vendor=$(cat "${sys_path}/../idVendor" 2>/dev/null || echo "?")
    product=$(cat "${sys_path}/../idProduct" 2>/dev/null || echo "?")
    echo "  ${dev}  (vendor=${vendor} product=${product})"
done
[ "$found" -eq 0 ] && echo "  (brak ttyUSB*/ttyACM* — lidar niepodłączony albo niewykryty)"

echo
echo "== Ostatnie zdarzenia USB w dmesg =="
dmesg | grep -iE "usb|tty|ftdi|cp210|ch340" | tail -20 || echo "(brak wpisów / brak dostępu do dmesg)"

echo
echo "== lsusb =="
lsusb
