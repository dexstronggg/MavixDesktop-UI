#!/bin/sh
# Build a single-file Linux binary of MavixDesktop via PyInstaller.
# Produces dist/mavixdesktop-linux. Run from the repo root.
set -e

if ! command -v pyinstaller >/dev/null 2>&1; then
    echo "pyinstaller not found. Install with: pip install pyinstaller"
    exit 1
fi

pyinstaller mavixdesktop.spec --clean --noconfirm

if [ -f dist/mavixdesktop ]; then
    mv dist/mavixdesktop dist/mavixdesktop-linux
fi
echo
echo "Build done: dist/mavixdesktop-linux ($(du -h dist/mavixdesktop-linux | cut -f1))"
