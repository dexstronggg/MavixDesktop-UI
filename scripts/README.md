# Сборка MavixDesktop

Скрипты в этой папке собирают single-file PyInstaller-бинари для распространения через MavixServer.

| Скрипт | Платформа | Выход |
|---|---|---|
| `build_binary.sh` | Linux | `dist/mavixdesktop-linux` |
| `build_windows.ps1` | Windows | `dist\mavixdesktop.exe` |
| `_make_icon.py` | — | генератор `.ico` / `.png` Mavix-логотипа на Pillow+NumPy (используется при необходимости перегенерации иконок) |

Обе сборки используют общий `mavixdesktop.spec` в корне репозитория. Подробный workflow и куда класть готовые артефакты — см. `../../BUILD.md` (в корне `MavixProject/`).

## Linux

```bash
cd MavixDesktop-UI
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pyinstaller
./scripts/build_binary.sh
```

Для PyInstaller на Debian/Ubuntu: `sudo apt install -y patchelf binutils`.

Результат: `dist/mavixdesktop-linux` (~200–280 МБ). Кладётся в `MavixServer/prebuilt/mavixdesktop-linux`, сервер отдаёт его через `GET /api/v1/builds/desktop?build_type=deb`.

## Windows

В PowerShell:

```powershell
cd MavixDesktop-UI
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
pip install pyinstaller
.\scripts\build_windows.ps1
```

Результат: `dist\mavixdesktop.exe`. Передать оператору сервера — он положит файл в `MavixServer/prebuilt/mavixdesktop.exe`.

Особенности Windows:
- **SmartScreen** при первом запуске покажет «Windows protected your PC» (бинарник не подписан) → «Подробнее» → «Выполнить в любом случае».
- **Антивирусы** иногда флагают PyInstaller-bundle'ы как подозрительные (self-extraction в `%TEMP%`) — false positive. Добавить в исключения, если мешает.
- Если pip падает на `error: Microsoft Visual C++ 14.0 or greater is required` — поставить C++ Build Tools с visualstudio.microsoft.com.

## Архитектурная привязка

PyInstaller собирает бинарь под архитектуру хост-машины. Сборка на x86_64 работает только на x86_64; на arm64 нужна отдельная сборка. Кросс-компиляция не поддерживается.

## Иконка

`_make_icon.py` рисует Mavix-логотип через Pillow+NumPy без зависимости от PySide6 — headless. Multi-size `.ico` (16/24/32/48/64/128/256) собирается через `Image.save(..., format='ICO', sizes=...)`.

В spec-сборке иконка по умолчанию не подцепляется: если она нужна в exe, передайте `--icon` в `EXE(...)` внутри `mavixdesktop.spec` или вызовите `_make_icon.py` отдельно.

## Если что-то падает

- **Linux: «Qt platform plugin 'xcb' not found»** — при `--onefile` PyInstaller иногда не упаковывает все Qt-плагины. Решается через `collect_all('PySide6')` (он уже в spec'е).
- **Windows: «Qt platform plugin 'windows' not found»** — то же, `collect_all('PySide6')` в spec покрывает.
- **Windows: vcruntime140.dll** — нужен Microsoft Visual C++ Redistributable: https://aka.ms/vs/17/release/vc_redist.x64.exe
- Большие warnings про `libxcb-*`, `tzdata`, `pycparser.lextab/yacctab` в логе PyInstaller — безвредны.
