# Сборка MavixDesktop

Скрипты в этой папке собирают исполнимые артефакты MavixDesktop для распространения.

| Скрипт | Платформа | Выход | Назначение |
|---|---|---|---|
| `build_binary.sh`   | Linux   | `dist/mavixdesktop-linux` | single-file ELF — основная Linux-раздача |
| `build_windows.ps1` | Windows | `dist\mavixdesktop.exe`    | single-file PyInstaller-сборка под Windows |

Оба варианта читают общий корневой `mavixdesktop.spec` (`--onefile`).

## Linux (single-file бинарь)

```bash
cd MavixDesktop-UI
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pyinstaller
sudo apt install -y patchelf binutils    # системные зависимости PyInstaller
./scripts/build_binary.sh
```

Результат: `dist/mavixdesktop-linux` (single-file ELF, `--onefile`). Запускается
напрямую: `chmod +x mavixdesktop-linux && ./mavixdesktop-linux`. Системных
зависимостей не требует — всё внутри bundle.

Отправка на сервер (раздаётся через `/api/v1/builds/desktop`):

```bash
scp dist/mavixdesktop-linux root@SERVER:/srv/mavix/MavixServer/prebuilt/
```

или обёрткой `StartUp/build/build_desktop_linux.sh` (сборка + scp + restart app).

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

Результат: `dist\mavixdesktop.exe`. Положить на сервер в
`/srv/mavix/MavixServer/prebuilt/mavixdesktop.exe`.

Особенности Windows:
- **SmartScreen** при первом запуске покажет «Windows protected your PC»
  (бинарник не подписан) → «Подробнее» → «Выполнить в любом случае».
- **Антивирусы** иногда флагают PyInstaller-bundle'ы как подозрительные
  (self-extraction в `%TEMP%`) — false positive. Добавить в исключения.
- Если pip падает на `error: Microsoft Visual C++ 14.0 or greater is required`
  — поставить C++ Build Tools с visualstudio.microsoft.com.

## Архитектурная привязка

PyInstaller собирает бинарь под архитектуру хост-машины. Сборка на x86_64
работает только на x86_64; на arm64 нужна отдельная сборка на arm64-машине.
Кросс-компиляция не поддерживается.

## Если что-то падает

- **Linux: «Qt platform plugin 'xcb' not found»** — при `--onefile` PyInstaller
  иногда не упаковывает все Qt-плагины. Решается через `collect_all('PySide6')`
  (он уже в spec'е).
- **Windows: «Qt platform plugin 'windows' not found»** — то же,
  `collect_all('PySide6')` в spec покрывает.
- **Windows: vcruntime140.dll** — нужен Microsoft Visual C++ Redistributable:
  https://aka.ms/vs/17/release/vc_redist.x64.exe
- Большие warnings про `libxcb-*`, `tzdata`, `pycparser.lextab/yacctab` в логе
  PyInstaller — безвредны.
