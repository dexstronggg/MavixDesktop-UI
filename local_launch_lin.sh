#!/usr/bin/env bash
# Локальный запуск MavixDesktop (наземная станция) на Linux.
# Требуется запущенный MavixServer на http://localhost:8000.
#
# Учётная запись та же, под которой зарегистрирован борт:
# по умолчанию dev@example.com / devpassword (см. MavixBoard/local_launch_lin.sh).
#
# Использование:  ./local_launch_lin.sh
#                 ./local_launch_lin.sh --demo       мок-данные, без сервера
#                 ./local_launch_lin.sh --headless   без GUI
# Полный сброс:   rm -rf .venv .env && ./local_launch_lin.sh

set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

VENV=.venv
PY="$VENV/bin/python"
STAMP="$VENV/.mavix-deps"
SERVER_URL="${MAVIX_SERVER_URL:-http://localhost:8000}"

command -v python3 >/dev/null 2>&1 || { echo "ОШИБКА: не найден python3" >&2; exit 1; }

if [ ! -d "$VENV" ]; then
  echo "==> создаю виртуальное окружение $VENV"
  python3 -m venv "$VENV"
fi

if [ ! -f "$STAMP" ] || [ pyproject.toml -nt "$STAMP" ]; then
  echo "==> устанавливаю зависимости (PySide6 весит много, первый раз долго)"
  "$VENV/bin/pip" install --upgrade pip --quiet
  "$VENV/bin/pip" install -e ".[dev]" --quiet
  touch "$STAMP"
fi

if [ ! -f .env ]; then
  echo "==> .env не найден — создаю локальный"
  cat > .env <<EOF
# Локальная конфигурация. Создана local_launch_lin.sh, в git не попадает.

SIGNAL_URL=$SERVER_URL

# Без STUN/TURN: борт и оператор на одной машине, хватает host-кандидатов.
# Пусто = взять то, что отдаст сервер по /api/v1/ice-servers (локально — тоже пусто).
STUN_SERVER=
TURN_SERVER=
TURN_USERNAME=
TURN_PASSWORD=
FORCE_RELAY=0

QGC_HOST=127.0.0.1
QGC_PORT=14550
QGC_BIND_PORT=0

KEYRING_SERVICE=mavixdesktop-local
DEBUG=0
EOF
fi

if [ "${1:-}" != "--demo" ]; then
  if ! "$PY" - "$SERVER_URL" <<'PY'
import sys
import urllib.request

url = sys.argv[1].rstrip('/') + '/api/v1/health'
try:
    with urllib.request.urlopen(url, timeout=3) as resp:
        sys.exit(0 if resp.status == 200 else 1)
except Exception:
    sys.exit(1)
PY
  then
    echo "ВНИМАНИЕ: сервер не отвечает на $SERVER_URL — приложение уйдёт в демо-режим." >&2
    echo "          Запустите ../MavixServer/local_launch_lin.sh, если это не то, что нужно." >&2
  fi
fi

echo "==> старт наземной станции"
exec "$PY" -m mavixdesktop "$@"
