# Сборка MavixDesktop

Скрипты в этой папке собирают исполнимые артефакты MavixDesktop для распространения.

| Скрипт | Платформа | Выход | Назначение |
|---|---|---|---|
| `build_appimage.sh` | Linux | `dist/Mavix-Desktop-x86_64.AppImage` | **основная Linux-раздача** (portable, с иконкой и .desktop) |
| `build_binary.sh`   | Linux | `dist/mavixdesktop-linux` | голый single-file ELF для разработки / отладки |
| `build_windows.ps1` | Windows | `dist\mavixdesktop.exe` | single-file PyInstaller-сборка под Windows |
| `_make_icon.py`     | —       | `.ico` / `.png` Mavix-логотипа на Pillow+NumPy | используется AppImage- и Windows-сборкой |

Все три PyInstaller-варианта читают общий корневой `mavixdesktop.spec` (build_appimage.sh при этом генерирует на лету временный spec-вариант `--onedir`, потому что AppImage требует развёрнутый bundle, а не одно-файловый exe).

## Linux — AppImage (рекомендуется)

```bash
cd MavixDesktop-UI
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pyinstaller pillow numpy
sudo apt install -y patchelf binutils wget    # системные зависимости PyInstaller + загрузка appimagetool
./scripts/build_appimage.sh
```

При первом запуске скрипт скачает `appimagetool-x86_64.AppImage` в `.build-cache/` (требуется интернет).

Результат: `dist/Mavix-Desktop-x86_64.AppImage` (~120–160 МБ — из бандла
вырезаны неиспользуемые модули Qt: QtWebEngine/Quick/QML/3D/Designer/Pdf/
Multimedia, см. фильтр в `mavixdesktop.spec`). Дистрибутив раздаёт **MavixServer**
по `/api/v1/builds/desktop?build_type=deb` из каталога `BUILDS_PREBUILT_DIR`
(дефолт `/srv/mavix/prebuilt`) под именем `mavixdesktop-linux` — **без расширения**:

```bash
cp dist/Mavix-Desktop-x86_64.AppImage "${BUILDS_PREBUILT_DIR:-/srv/mavix/prebuilt}/mavixdesktop-linux"
# в monorepo-разработке BUILDS_PREBUILT_DIR обычно указывает на ../MavixServer/prebuilt
```

Пользователь скачивает файл, делает `chmod +x`, и запускает напрямую — никаких системных зависимостей не требуется (FUSE для AppImage, обычно уже стоит; иначе `--appimage-extract-and-run` как fallback).

### Почему AppImage, а не голый бинарь

- Внутри AppImage есть `.desktop` + иконка → интегрируется в меню приложений (через `appimaged`/`appimagelauncher`, опционально).
- AppImage-формат самораспаковывающийся через FUSE — старт без явной установки.
- PyInstaller bundle внутри собран в `--onedir` режиме: распаковки в `/tmp/_MEIxxxx` при каждом запуске нет, старт быстрее, чем у `mavixdesktop-linux`.

## Linux — голый бинарь (разработка)

`build_binary.sh` остаётся как путь для разработки и отладки. Он быстрее в проверке (нет AppImage-обёртки) и не требует интернета.

```bash
./scripts/build_binary.sh
```

Результат: `dist/mavixdesktop-linux` (single-file ELF, `--onefile` PyInstaller). Запускается напрямую, без иконки и .desktop.

Для PyInstaller на Debian/Ubuntu: `sudo apt install -y patchelf binutils`.

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

Результат: `dist\mavixdesktop.exe`. Передать оператору сервера — он положит файл в `BUILDS_PREBUILT_DIR` (дефолт `/srv/mavix/prebuilt`) под именем `mavixdesktop.exe`; раздаётся **MavixServer** по `/api/v1/builds/desktop?build_type=exe`.

Особенности Windows:
- **SmartScreen** при первом запуске покажет «Windows protected your PC» (бинарник не подписан) → «Подробнее» → «Выполнить в любом случае».
- **Антивирусы** иногда флагают PyInstaller-bundle'ы как подозрительные (self-extraction в `%TEMP%`) — false positive. Добавить в исключения, если мешает.
- Если pip падает на `error: Microsoft Visual C++ 14.0 or greater is required` — поставить C++ Build Tools с visualstudio.microsoft.com.

## Архитектурная привязка

PyInstaller собирает бинарь под архитектуру хост-машины. Сборка на x86_64 работает только на x86_64; на arm64 нужна отдельная сборка (запуск `ARCH=aarch64 ./scripts/build_appimage.sh` на arm64-машине). Кросс-компиляция не поддерживается.

## Иконка

`_make_icon.py` рисует Mavix-логотип через Pillow+NumPy без зависимости от PySide6 — headless. Поддерживает оба формата:

```bash
python scripts/_make_icon.py --format png --output dist/icon.png --size 256
python scripts/_make_icon.py --format ico --output dist/icon.ico
```

Multi-size `.ico` (16/24/32/48/64/128/256) собирается через `Image.save(..., format='ICO', sizes=...)`. Используется build_appimage.sh (PNG 256x256) и потенциально Windows-сборкой (ICO).

## Если что-то падает

- **Linux: «Qt platform plugin 'xcb' not found»** — при `--onefile` PyInstaller иногда не упаковывает все Qt-плагины. Решается через `collect_all('PySide6')` (он уже в spec'е; фильтр размера трогает только заведомо неиспользуемые модули и плагин `platforms` сохраняет).
- **«Module ... QtWebEngine/QtQuick/QtMultimedia not found» после ужатия** — эти модули намеренно вырезаны из бандла (`_QT_DROP` в `mavixdesktop.spec`). Если код реально начал их использовать — убери соответствующий токен из `_QT_DROP` и модуль из `excludes`.
- **Linux AppImage: «AppImage requires FUSE»** на старых дистрибутивах — либо `sudo apt install libfuse2`, либо запуск через `./Mavix-Desktop-x86_64.AppImage --appimage-extract-and-run`.
- **Windows: «Qt platform plugin 'windows' not found»** — то же, `collect_all('PySide6')` в spec покрывает.
- **Windows: vcruntime140.dll** — нужен Microsoft Visual C++ Redistributable: https://aka.ms/vs/17/release/vc_redist.x64.exe
- **appimagetool: «AppImage requires FUSE to run»** в Docker / CI — запустите его сами с `--appimage-extract-and-run`, или используйте `--no-appstream`-флаг.
- Большие warnings про `libxcb-*`, `tzdata`, `pycparser.lextab/yacctab` в логе PyInstaller — безвредны.
