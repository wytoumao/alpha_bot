#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PATH="${PROJECT_ROOT}/.venv"

python3 -m venv "${VENV_PATH}"
source "${VENV_PATH}/bin/activate"

pip install --upgrade pip
pip install -e "${PROJECT_ROOT}"

"${VENV_PATH}/bin/playwright" install chromium

echo "Bootstrap complete. Activate the virtualenv with: source ${VENV_PATH}/bin/activate"
