# Build MavixDesktop for Windows via PyInstaller.
#
# Requirements:
#   * Python 3.11+ installed and available in PATH
#   * .venv created and populated with project dependencies
#     (see README: pip install -e ".[dev]")
#
# Usage (from MavixDesktop-UI root):
#   .\scripts\build_windows.ps1
#
# Output: dist\mavix-desktop-windows.exe — one-file, no console, Mavix icon.

$ErrorActionPreference = 'Stop'

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = Split-Path -Parent $ScriptDir

Push-Location $ProjectRoot
try {
    # -- Check venv -------------------------------------------------------
    if (-not (Test-Path '.venv')) {
        Write-Host 'ERROR: .venv not found. Create it first:' -ForegroundColor Red
        Write-Host '  python -m venv .venv'
        Write-Host '  .venv\Scripts\Activate.ps1'
        Write-Host '  pip install -e ".[dev]"'
        exit 1
    }
    $VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path $VenvPython)) {
        Write-Host "ERROR: $VenvPython not found" -ForegroundColor Red
        exit 1
    }

    # -- Build dependencies -----------------------------------------------
    Write-Host '[1/3] Installing build dependencies...' -ForegroundColor Cyan
    & $VenvPython -m pip install --quiet --upgrade pip pyinstaller pillow
    if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }

    # -- Icon -------------------------------------------------------------
    Write-Host '[2/3] Generating icon...' -ForegroundColor Cyan
    New-Item -Force -ItemType Directory -Path 'dist' | Out-Null
    $IconPath = Join-Path $ProjectRoot 'dist\build-icon.ico'
    & $VenvPython 'scripts\_make_icon.py' --format ico --output $IconPath
    if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed' }

    # -- PyInstaller ------------------------------------------------------
    Write-Host '[3/3] Running PyInstaller (this may take a few minutes)...' -ForegroundColor Cyan
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
        throw "Expected output not found: $OutExe"
    }

    Write-Host ''
    Write-Host "OK Build ready: $OutExe" -ForegroundColor Green
    Write-Host "   Copy to MavixWeb\public\downloads\ to serve via the website."
}
finally {
    Pop-Location
}
