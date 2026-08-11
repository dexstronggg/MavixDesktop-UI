# Локальный запуск MavixDesktop (наземная станция) на Windows.
# Порт local_launch_lin.sh; поведение и имена файлов совпадают.
# Требуется запущенный MavixServer на http://localhost:8000.
#
# Учётная запись та же, под которой зарегистрирован борт:
# по умолчанию dev@example.com / devpassword (см. MavixBoard/local_launch_lin.sh).
#
# Использование:  .\local_launch_win.ps1
#                 .\local_launch_win.ps1 --demo       мок-данные, без сервера
#                 .\local_launch_win.ps1 --headless   без GUI
# Полный сброс:   Remove-Item -Recurse -Force .venv, .env; .\local_launch_win.ps1
#
# Если PowerShell отказывается запускать скрипт, разрешите это для текущего
# пользователя (одноразово):
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$Venv = '.venv'
$Py = Join-Path $Venv 'Scripts\python.exe'
$Pip = Join-Path $Venv 'Scripts\pip.exe'
$Stamp = Join-Path $Venv '.mavix-deps'
$ServerUrl = if ($env:MAVIX_SERVER_URL) { $env:MAVIX_SERVER_URL } else { 'http://localhost:8000' }

# py -3 надёжнее: python.exe в PATH часто оказывается заглушкой из Microsoft Store
if (Get-Command py -ErrorAction SilentlyContinue) {
    $PyExe = 'py'
    $PyArgs = @('-3')
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PyExe = 'python'
    $PyArgs = @()
} else {
    Write-Error 'ОШИБКА: не найден Python. Поставьте Python 3.11+ с python.org'
    exit 1
}

if (-not (Test-Path -LiteralPath $Venv)) {
    Write-Host "==> создаю виртуальное окружение $Venv"
    & $PyExe @PyArgs -m venv $Venv
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$needDeps = -not (Test-Path -LiteralPath $Stamp)
if (-not $needDeps) {
    $needDeps = (Get-Item pyproject.toml).LastWriteTimeUtc -gt (Get-Item $Stamp).LastWriteTimeUtc
}
if ($needDeps) {
    Write-Host '==> устанавливаю зависимости (PySide6 весит много, первый раз долго)'
    & $Pip install --upgrade pip --quiet
    & $Pip install -e '.[dev]' --quiet
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    New-Item -ItemType File -Path $Stamp -Force | Out-Null
}

if (-not (Test-Path -LiteralPath '.env')) {
    Write-Host '==> .env не найден — создаю локальный'
    $envText = @"
# Локальная конфигурация. Создана local_launch_win.ps1, в git не попадает.

SIGNAL_URL=$ServerUrl

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
"@
    # без BOM: python-dotenv иначе прочитает первый ключ вместе с меткой
    [System.IO.File]::WriteAllText(
        (Join-Path $PSScriptRoot '.env'),
        $envText,
        (New-Object System.Text.UTF8Encoding $false)
    )
}

if ($args.Count -eq 0 -or $args[0] -ne '--demo') {
    try {
        $resp = Invoke-WebRequest -Uri "$($ServerUrl.TrimEnd('/'))/api/v1/health" `
            -TimeoutSec 3 -UseBasicParsing
        $alive = $resp.StatusCode -eq 200
    } catch {
        $alive = $false
    }
    if (-not $alive) {
        Write-Warning "сервер не отвечает на $ServerUrl — приложение уйдёт в демо-режим."
        Write-Warning '          Запустите MavixServer, если это не то, что нужно.'
    }
}

Write-Host '==> старт наземной станции'
& $Py -m mavixdesktop @args
exit $LASTEXITCODE
