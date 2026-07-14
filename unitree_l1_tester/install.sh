#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ARCH="$(uname -m)"

if [[ "$ARCH" != "aarch64" ]]; then
  echo "BLAD: oficjalne SDK Unitree L1 ma gotowa biblioteke dla aarch64 i x86_64."
  echo "Na Raspberry Pi zainstaluj 64-bitowy Raspberry Pi OS (uname -m powinno pokazac aarch64)."
  echo "Obecna architektura: $ARCH"
  exit 1
fi

sudo apt update
sudo apt install -y git cmake g++ build-essential lsof

PROJECT_DIR="${HOME}/unilidar_sdk"
SDK_DIR="${PROJECT_DIR}/unitree_lidar_sdk"

if [[ ! -d "${PROJECT_DIR}/.git" ]]; then
  git clone --depth 1 https://github.com/unitreerobotics/unilidar_sdk.git "${PROJECT_DIR}"
else
  git -C "${PROJECT_DIR}" pull --ff-only
fi

cp "${SCRIPT_DIR}/lidar_l1_tester.cpp" "${SDK_DIR}/examples/lidar_l1_tester.cpp"

if ! grep -q 'add_executable(lidar_l1_tester' "${SDK_DIR}/CMakeLists.txt"; then
  cat >> "${SDK_DIR}/CMakeLists.txt" <<'CMAKE'

add_executable(lidar_l1_tester
  examples/lidar_l1_tester.cpp
)
target_link_libraries(lidar_l1_tester libunitree_lidar_sdk.a)
CMAKE
fi

cmake -S "${SDK_DIR}" -B "${SDK_DIR}/build"
cmake --build "${SDK_DIR}/build" --target lidar_l1_tester -j2

sudo usermod -aG dialout "$USER"

mkdir -p "${HOME}/.local/bin"
cat > "${HOME}/.local/bin/unitree-l1-test" <<EOF
#!/usr/bin/env bash
exec "${SDK_DIR}/bin/lidar_l1_tester" "\$@"
EOF
chmod +x "${HOME}/.local/bin/unitree-l1-test"

echo
echo "Gotowe. Program: ${SDK_DIR}/bin/lidar_l1_tester"
echo "Skrot:          ${HOME}/.local/bin/unitree-l1-test"
echo
echo "Uruchomienie:"
echo "  ${SDK_DIR}/bin/lidar_l1_tester /dev/ttyUSB0"
echo
echo "Automatyczny test i wyjscie:"
echo "  ${SDK_DIR}/bin/lidar_l1_tester /dev/ttyUSB0 --autotest"
echo
echo "Jesli dopiero dodano Cie do grupy dialout, wyloguj sie i zaloguj ponownie albo wykonaj:"
echo "  newgrp dialout"
