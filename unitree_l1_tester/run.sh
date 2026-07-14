#!/usr/bin/env bash
set -euo pipefail

BIN="${HOME}/unilidar_sdk/unitree_lidar_sdk/bin/lidar_l1_tester"

if [[ ! -x "$BIN" ]]; then
  echo "Nie znaleziono programu: $BIN"
  echo "Najpierw uruchom ./install.sh"
  exit 1
fi

PORT="${1:-}"
if [[ -z "$PORT" ]]; then
  shopt -s nullglob
  by_id=(/dev/serial/by-id/*)
  usb=(/dev/ttyUSB*)
  acm=(/dev/ttyACM*)
  candidates=("${by_id[@]}" "${usb[@]}" "${acm[@]}")
  shopt -u nullglob

  if (( ${#candidates[@]} == 0 )); then
    echo "Nie znaleziono /dev/ttyUSB*, /dev/ttyACM* ani /dev/serial/by-id/*."
    exit 2
  fi
  PORT="${candidates[0]}"
fi

shift $(( $# > 0 ? 1 : 0 ))
echo "Uzywam portu: $PORT"
exec "$BIN" "$PORT" "$@"
