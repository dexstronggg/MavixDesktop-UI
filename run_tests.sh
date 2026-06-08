#!/bin/bash
# Запуск всех тестов приложения оператора (модульные + интеграционные) с покрытием.
# Qt работает в offscreen-режиме (без дисплея). На голой системе могут
# потребоваться libgl1 / libegl1 / libxkbcommon0.
set -e
cd "$(dirname "$0")"
[ -d .venv ] && source .venv/bin/activate
export QT_QPA_PLATFORM=offscreen
python -m pytest --cov=src/mavixdesktop --cov-report=term-missing --cov-report=html -q "$@"
echo
echo "HTML-отчёт покрытия: htmlcov/index.html"
