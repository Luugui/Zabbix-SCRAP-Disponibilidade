#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${INSTALL_DIR:-/opt/zabbix-report}"
SERVICE_USER="${SERVICE_USER:-zabbix-report}"
ENV_DIR="/etc/zabbix-report"
VENV_DIR="${INSTALL_DIR}/.venv"
BROWSER_DIR="${INSTALL_DIR}/.browsers"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Execute como root ou com sudo: sudo $0" >&2
  exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "Este instalador requer systemd." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv python3-pip rsync

if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --home-dir "${INSTALL_DIR}" --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${INSTALL_DIR}"
install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${ENV_DIR}"

# Copia somente os arquivos necessários para não carregar o .git e artefatos locais.
rsync -a --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '.browsers' \
  --exclude 'logs' \
  --exclude 'reports' \
  "${PROJECT_SOURCE}/" "${INSTALL_DIR}/"

python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"

mkdir -p "${BROWSER_DIR}"
PLAYWRIGHT_BROWSERS_PATH="${BROWSER_DIR}" "${VENV_DIR}/bin/python" -m playwright install --with-deps chromium

if [[ ! -f "${ENV_DIR}/zabbix-report.env" ]]; then
  install -m 600 "${INSTALL_DIR}/deploy/zabbix-report.env.example" "${ENV_DIR}/zabbix-report.env"
  echo "Arquivo criado: ${ENV_DIR}/zabbix-report.env"
  echo "Edite as credenciais antes da primeira execução."
fi

install -m 644 "${INSTALL_DIR}/deploy/zabbix-report.service" /etc/systemd/system/zabbix-report.service
install -m 644 "${INSTALL_DIR}/deploy/zabbix-report.timer" /etc/systemd/system/zabbix-report.timer
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"
chmod 700 "${INSTALL_DIR}/logs" "${INSTALL_DIR}/reports" 2>/dev/null || true

systemctl daemon-reload
systemctl enable zabbix-report.timer
systemctl restart zabbix-report.timer

echo
systemctl --no-pager status zabbix-report.timer || true
echo
echo "Instalação concluída. Edite ${ENV_DIR}/zabbix-report.env e execute:"
echo "  systemctl start zabbix-report.service"
