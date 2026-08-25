#!/usr/bin/env bash
# BreezySLAM nie jest publikowany na PyPI - trzeba go zbudowac ze zrodel
# (rozszerzenie C, pybreezyslam). Ten skrypt buduje go dla venv projektu
# i architektury/wersji Pythona, na ktorej jest uruchamiany (np. aarch64,
# Raspberry Pi 5).
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="${SCRIPT_DIR}/.venv/bin/python3"
BUILD_DIR="$(mktemp -d)"

if [[ ! -x "$VENV_PY" ]]; then
  echo "Nie znaleziono ${VENV_PY} - utworz najpierw venv projektu."
  exit 1
fi

git clone --depth 1 https://github.com/simondlevy/BreezySLAM.git "${BUILD_DIR}/BreezySLAM"

cd "${BUILD_DIR}/BreezySLAM/python"
"$VENV_PY" setup.py build_ext --inplace

SITE_PACKAGES="$("$VENV_PY" -c "import site; print(site.getsitepackages()[0])")"
cp pybreezyslam*.so "$SITE_PACKAGES/"
cp -r breezyslam "$SITE_PACKAGES/"

rm -rf "$BUILD_DIR"

"$VENV_PY" -c "
import pybreezyslam
from breezyslam.algorithms import RMHC_SLAM
from breezyslam.sensors import Laser
print('BreezySLAM zainstalowany poprawnie:', pybreezyslam.__file__)
"

echo "Gotowe."
