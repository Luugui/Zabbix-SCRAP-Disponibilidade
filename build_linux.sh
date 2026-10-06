#!/usr/bin/env bash
set -euo pipefail

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-sender.txt pyinstaller
python -m PyInstaller \
  --noconfirm \
  --clean \
  --onefile \
  --windowed \
  --collect-all customtkinter \
  --collect-all zabbix_utils \
  --name zbx-sender \
  zbx_sender_app.py

echo "Executável criado em dist/zbx-sender"
