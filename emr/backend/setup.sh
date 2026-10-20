#!/usr/bin/env bash
set -euo pipefail
VENV=~/venv/emr
[ -d "$VENV" ] || python3 -m venv --system-site-packages "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install --upgrade pip
pip install -r requirements.txt
echo "done. activate with: source $VENV/bin/activate"
