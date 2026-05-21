# Сборка MavixDesktop под Windows через PyInstaller.
#
# Требования:
#   * Python 3.11+ установлен и доступен в PATH
#   * .venv создан и заполнен зависимостями проекта
#     (см. README: pip install -e ".[dev]")
#
# Использование (из корня MavixDesktop-UI):
#   .\scripts\build_windows.ps1
#
# Результат: dist\mavix-desktop-windows.exe — one-file, без консоли,
# с Mavix-иконкой. Готов к копированию в MavixWeb\public\downloads\.

$ErrorActionPreference = 'Stop'

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = Split-Path -Parent $ScriptDir

Push-Location $ProjectRoot
try {
    # ── Проверка venv ─────────────────────────────────────────────────────────
    if (-not (Test-Path '.venv')) {
        Write-Host 'ERROR: .venv не найден. Создайте окружение:' -ForegroundColor Red
        Write-Host '  python -m venv .venv'
        Write-Host '  .venv\Scripts\Activate.ps1'
        Write-Host '  pip install -e ".[dev]"'
        exit 1
    }
    $VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path $VenvPython)) {
        Write-Host "ERROR: $VenvPython не найден" -ForegroundColor Red
        exit 1
    }

    # ── Build-зависимости (PyInstaller + Pillow для multi-size ICO) ───────────
    Write-Host '[1/3] Установка build-зависимостей...' -ForegroundColor Cyan
    & $VenvPython -m pip install --quiet --upgrade pip pyinstaller pillow
    if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }

    # ── Иконка ────────────────────────────────────────────────────────────────
    Write-Host '[2/3] Генерация иконки...' -ForegroundColor Cyan
    New-Item -Force -ItemType Directory -Path 'dist' | Out-Null
    $IconPath = Join-Path $ProjectRoot 'dist\build-icon.ico'
    & $VenvPython 'scripts\_make_icon.py' --format ico --output $IconPath
    if ($LASTEXITCODE -ne 0) { throw 'icon generation failed' }

    # ── PyInstaller ───────────────────────────────────────────────────────────
    Write-Host '[3/3] PyInstaller (это займёт пару минут)...' -ForegroundColor Cyan
    # --onefile: один .exe, само-распаковывается в %TEMP% при запуске
    # --noconsole: без чёрного окна консоли при старте (windowed app)
    # --add-data: SVG-иконки UI должны быть в bundle'е, runtime читает их
    #             через Path(__file__).parent.parent / 'icons'. Разделитель
    #             на Windows — ';' (на Linux/macOS — ':').
    & $VenvPython -m PyInstaller `
        --noconfirm `
        --onefile `
        --noconsole `
        --icon $IconPath `
        --name 'mavix-desktop-windows' `
        --add-data 'src\mavixdesktop\ui\icons;mavixdesktop\ui\icons' `
        'src\mavixdesktop\__main__.py'
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }

    $OutExe = Join-Path $ProjectRoot 'dist\mavix-desktop-windows.exe'
    if (-not (Test-Path $OutExe)) {
        throw "Ожидаемый файл не создан: $OutExe"
    }

    Write-Host ''
    Write-Host "OK Сборка готова: $OutExe" -ForegroundColor Green
    Write-Host "   Скопируйте в MavixWeb\public\downloads\ для раздачи через сайт."
}
finally {
    Pop-Location
}
