$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -m venv .venv
}
$python = ".venv\Scripts\python.exe"
& $python -m pip install --upgrade pip
& $python -m pip install -r requirements-sender.txt pyinstaller
& $python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --collect-all customtkinter `
  --collect-all zabbix_utils `
  --name zbx-sender `
  zbx_sender_app.py

Write-Host "Executável criado em dist/zbx-sender.exe"
