# MavixDesktop

Приложение оператора (GCS) для системы Mavix: подключается к MavixServer, поднимает WebRTC-сессию с дроном (MavixBoard), показывает видео с камер и передаёт джойстик/MAVLink на полётный контроллер. PySide6 + aiortc + asyncio.

## Запуск

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env-example .env
.venv/bin/python -m mavixdesktop
```

Без доступного сервера приложение само переключается в демо-режим (мок-данные, любой email/пароль). Флаги: `--demo` — форсировать демо-режим, `--headless` — без GUI (только координатор).

Скрипты локального запуска делают всё то же самое одной командой — создают venv, ставят зависимости, пишут локальный `.env` и проверяют, отвечает ли сервер:

```bash
./local_launch_lin.sh              # Linux
```

```powershell
.\local_launch_win.ps1             # Windows
```

Флаги передаются насквозь: `.\local_launch_win.ps1 --demo`. Если PowerShell откажется выполнять скрипт, один раз разрешите: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Подробнее

- [TECHNICAL.md](TECHNICAL.md) — архитектура, установка (`.deb`/dev), конфигурация, debug-режим.
- [USER_GUIDE.md](USER_GUIDE.md) — руководство оператора.
- [`scripts/BUILD.md`](scripts/BUILD.md) — как собрать и разложить дистрибутивы (Linux-бинарь, Windows `.exe` локально/через GitHub Actions).
