# Сборка дистрибутивов MavixDesktop

Скрипты в этой папке собирают распространяемые бинарники для пользователей:

| Скрипт | Платформа | Выход | Что внутри |
|---|---|---|---|
| `build_windows.ps1` | Windows | `dist\mavix-desktop-windows.exe` | one-file PyInstaller, без консольного окна, с иконкой |
| `build_linux.sh`    | Linux   | `dist/mavix-desktop-linux.deb`   | one-file PyInstaller + `.deb`-пакет с `.desktop`-файлом и иконкой в меню |
| `_make_icon.py`     | —       | (вызывается из build-скриптов) | генератор `.ico` / `.png` Mavix-логотипа на Pillow+NumPy |

Имена выходных файлов **точно совпадают** с whitelist-маршрутами MavixWeb
(`/downloads/mavix-desktop-{windows.exe,linux.deb}`) — копирование в
`MavixWeb/public/downloads/` работает 1-в-1.

---

## Сборка под Linux (`.deb`)

### Требования

- Python 3.11+ и пакет `python3-venv` (на Debian/Ubuntu: `sudo apt install python3-venv`)
- `dpkg-deb` (в Debian/Ubuntu идёт по умолчанию; иначе `sudo apt install dpkg-dev`)

### Шаги

```bash
cd MavixDesktop-UI

# Один раз — venv и зависимости проекта (~5 минут)
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# Сборка (≈2-3 минуты)
./scripts/build_linux.sh
```

В `dist/`:
- `mavix-desktop` — голый бинарник
- `mavix-desktop-linux.deb` — пакет для раздачи

### Локальная установка для проверки

```bash
sudo dpkg -i dist/mavix-desktop-linux.deb
mavix-desktop          # запуск из терминала
# Или из меню приложений: Mavix Desktop
```

Деинсталляция: `sudo dpkg -r mavix-desktop`.

### Что .deb разворачивает

| Файл | Где оказывается |
|---|---|
| Бинарник | `/opt/mavix-desktop/mavix-desktop` |
| Symlink в PATH | `/usr/local/bin/mavix-desktop` |
| `.desktop` (меню приложений) | `/usr/share/applications/mavix-desktop.desktop` |
| Иконка 256×256 | `/usr/share/icons/hicolor/256x256/apps/mavix-desktop.png` |

---

## Сборка под Windows (`.exe`)

### Требования

- Python 3.11+ из [python.org](https://www.python.org/downloads/windows/), при установке отметить галку **«Add Python to PATH»**
- PowerShell (есть в Windows 10/11 из коробки)

### Шаги (PowerShell)

```powershell
cd MavixDesktop-UI

# Один раз — venv и зависимости (~5-10 минут, PySide6 ~200 MB)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# Если PowerShell ругается на Activate.ps1 — разрешить выполнение
# скриптов для текущего пользователя:
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

# Сборка (≈3-5 минут)
.\scripts\build_windows.ps1
```

Готовый файл: `dist\mavix-desktop-windows.exe` (~95 MB).

### Локальная проверка .exe

```powershell
.\dist\mavix-desktop-windows.exe --demo
```

⚠ **SmartScreen** при первом запуске покажет «Windows protected your PC»
(бинарник не подписан) → «Подробнее» → «Выполнить в любом случае». Нормально.

⚠ **Антивирусы** иногда флагают PyInstaller-bundle'ы как подозрительные
(self-extraction в `%TEMP%`) — false positive. Добавить в исключения если мешает.

---

## Раздача через MavixWeb

После сборки на любой из платформ — копируем артефакт в
[MavixWeb](https://github.com/dexstronggg/MavixWeb)`/public/downloads/`:

```bash
# Linux
cp dist/mavix-desktop-linux.deb ../MavixWeb/public/downloads/

# Windows (PowerShell)
copy dist\mavix-desktop-windows.exe ..\MavixWeb\public\downloads\
```

После этого кнопки «Linux (.deb)» / «Windows (.exe)» на странице
`/dashboard/software` раздают файлы через whitelist-маршруты Express
(см. `MavixWeb/server.js`).

### Деплой на production

На production-хосте MavixWeb папка `public/downloads/` находится там же,
куда установлен веб-сервер. Артефакты заливаются туда любым способом
(scp/rsync/SFTP/CI). Файлы в git **не коммитятся** — `public/downloads/*`
в `.gitignore` (GitHub не любит файлы >100 MB, и нет смысла хранить
сборки в репозитории).

---

## Иконка приложения

`_make_icon.py` рисует Mavix-логотип (cyan-градиентный rounded square +
бел/тёмная «M») через **Pillow + NumPy**, без зависимости от PySide6.

Это сознательное решение: PySide6 на сборочной машине требует libGL.so.1
(mesa) уже при импорте `PySide6.QtGui` — мы не хотим тянуть mesa на CI
просто для генерации иконки. Pillow-вариант полностью headless.

Multi-size `.ico` (16/24/32/48/64/128/256) собирается одной командой
через `Image.save(..., format='ICO', sizes=...)` — Windows сам ресолвит
нужный размер по контексту (tray vs alt-tab vs explorer).

---

## Если что-то падает

- **Linux**: `_make_icon.py` падает на `ModuleNotFoundError: No module named 'PIL'` — build-скрипт должен сам поставить Pillow в venv. Если ставится не туда — проверь что активирован правильный `.venv`.
- **Windows**: PyInstaller не находит `vcruntime140.dll` при запуске собранного `.exe` — нужен Microsoft Visual C++ Redistributable: <https://aka.ms/vs/17/release/vc_redist.x64.exe>
- **Windows**: «Qt platform plugin 'windows' not found» — PyInstaller не упаковал Qt platform plugin. Решается флагом `--collect-all PySide6` в `build_windows.ps1` (пока не требовалось).
- **Большие warnings про libxcb-***, **tzdata, pycparser.lextab/yacctab** в логе PyInstaller — безвредны, можно игнорировать. Артефакт собирается всё равно.
