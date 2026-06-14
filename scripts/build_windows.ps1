# Build MavixDesktop for Windows via PyInstaller.
#
# Requirements:
#   * Python 3.12+ installed and available in PATH
#   * .venv created with project dependencies
#       python -m venv .venv
#       .\.venv\Scripts\Activate.ps1
#       pip install -e .
#       pip install pyinstaller
#
# Usage (from MavixDesktop-UI root):
#   .\scripts\build_windows.ps1
#
# Output: dist\mavixdesktop.exe — single-file PyInstaller build using
# mavixdesktop.spec (no console window). Передайте .exe оператору
# серверного развёртывания: его кладут в MavixServer/prebuilt/.

$ErrorActionPreference = 'Stop'

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = Split-Path -Parent $ScriptDir

Push-Location $ProjectRoot
try {
    if (-not (Test-Path '.venv')) {
        Write-Host 'ERROR: .venv not found. Create it first:' -ForegroundColor Red
        Write-Host '  python -m venv .venv'
        Write-Host '  .\.venv\Scripts\Activate.ps1'
        Write-Host '  pip install -e .'
        Write-Host '  pip install pyinstaller'
        exit 1
    }
    $VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path $VenvPython)) {
        Write-Host "ERROR: $VenvPython not found" -ForegroundColor Red
        exit 1
    }

    Write-Host 'Running PyInstaller (this may take a few minutes)...' -ForegroundColor Cyan
    & $VenvPython -m PyInstaller mavixdesktop.spec --clean --noconfirm
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }

    $OutExe = Join-Path $ProjectRoot 'dist\mavixdesktop.exe'
    if (-not (Test-Path $OutExe)) {
        throw "Expected output not found: $OutExe"
    }

    Write-Host ''
    Write-Host "OK Build ready: $OutExe" -ForegroundColor Green
    Write-Host "   Передайте файл оператору сервера: положить в BUILDS_PREBUILT_DIR (дефолт /srv/mavix/prebuilt) как mavixdesktop.exe."
    Write-Host "   Раздаётся MavixServer по /api/v1/builds/desktop?build_type=exe."
}
finally {
    Pop-Location
}
