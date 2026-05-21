#!/usr/bin/env bash
# Сборка MavixDesktop под Linux: PyInstaller (one-file binary) + dpkg-deb.
#
# Результат: dist/mavix-desktop-linux.deb — устанавливается через
#   sudo dpkg -i mavix-desktop-linux.deb
# Кладёт бинарник в /opt/mavix-desktop/, регистрирует .desktop файл
# и иконку в системе (хорошо вписывается в меню приложений GNOME/KDE).
#
# Требования:
#   * Python 3.11+, .venv с зависимостями проекта (pip install -e ".[dev]")
#   * dpkg-deb в PATH (на Debian/Ubuntu — установлен по умолчанию)
#
# Использование из корня MavixDesktop-UI:
#   ./scripts/build_linux.sh

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( dirname "$SCRIPT_DIR" )"
cd "$PROJECT_ROOT"

# ── Проверки окружения ───────────────────────────────────────────────────────
if [ ! -d .venv ]; then
    echo "ERROR: .venv не найден. Создайте окружение:" >&2
    echo "  python3 -m venv .venv" >&2
    echo "  .venv/bin/pip install -e '.[dev]'" >&2
    exit 1
fi
VENV_PY=".venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
    echo "ERROR: $VENV_PY не найден или не executable" >&2
    exit 1
fi
if ! command -v dpkg-deb >/dev/null 2>&1; then
    echo "ERROR: dpkg-deb не найден. Установите: sudo apt install dpkg-dev" >&2
    exit 1
fi

# ── Build-зависимости ────────────────────────────────────────────────────────
echo "[1/4] Установка build-зависимостей..."
"$VENV_PY" -m pip install --quiet --upgrade pip pyinstaller pillow

# ── Иконка PNG ───────────────────────────────────────────────────────────────
echo "[2/4] Генерация иконки..."
mkdir -p dist
ICON_PATH="dist/build-icon.png"
"$VENV_PY" scripts/_make_icon.py --format png --output "$ICON_PATH" --size 256

# ── PyInstaller (one-file binary) ────────────────────────────────────────────
echo "[3/4] PyInstaller (это займёт пару минут)..."
# --onefile: единый исполняемый файл, само-распаковывается в /tmp при запуске
# --add-data: SVG-иконки UI должны быть в bundle'е, runtime читает их
#             через Path(__file__).parent.parent / 'icons'. Разделитель
#             на Linux — ':' (на Windows — ';').
# Конкретный --icon на Linux нерелевантен (PyInstaller под Linux его
# игнорирует — для X11/Wayland иконка приходит из .desktop файла).
"$VENV_PY" -m PyInstaller \
    --noconfirm \
    --onefile \
    --name "mavix-desktop" \
    --add-data "src/mavixdesktop/ui/icons:mavixdesktop/ui/icons" \
    src/mavixdesktop/__main__.py

BINARY="dist/mavix-desktop"
if [ ! -x "$BINARY" ]; then
    echo "ERROR: ожидаемый бинарник не создан: $BINARY" >&2
    exit 1
fi

# ── Сборка .deb ──────────────────────────────────────────────────────────────
echo "[4/4] Сборка .deb-пакета..."
STAGING="dist/deb-staging"
rm -rf "$STAGING"
mkdir -p "$STAGING/DEBIAN"
mkdir -p "$STAGING/opt/mavix-desktop"
mkdir -p "$STAGING/usr/share/applications"
mkdir -p "$STAGING/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$STAGING/usr/local/bin"

# Бинарник в /opt/mavix-desktop/ — каноническое место для third-party
# приложений. Symlink в /usr/local/bin/ даёт возможность запустить
# из терминала командой `mavix-desktop`.
cp "$BINARY" "$STAGING/opt/mavix-desktop/mavix-desktop"
chmod 755 "$STAGING/opt/mavix-desktop/mavix-desktop"
ln -sf /opt/mavix-desktop/mavix-desktop "$STAGING/usr/local/bin/mavix-desktop"

# Иконка по XDG (Icon=mavix-desktop в .desktop резолвится по имени)
cp "$ICON_PATH" "$STAGING/usr/share/icons/hicolor/256x256/apps/mavix-desktop.png"

# .desktop-файл для меню приложений (GNOME/KDE/XFCE)
cat > "$STAGING/usr/share/applications/mavix-desktop.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Mavix Desktop
GenericName=UAV Ground Control Station
Comment=Управление дронами Mavix через WebRTC
Exec=/opt/mavix-desktop/mavix-desktop
Icon=mavix-desktop
Terminal=false
Categories=Utility;Network;
StartupNotify=true
EOF
chmod 644 "$STAGING/usr/share/applications/mavix-desktop.desktop"

# DEBIAN/control: метаданные пакета. Версия тянется из pyproject.toml
# (если не нашли — fallback на 0.1.0).
VERSION="$(sed -nE 's/^version[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/p' pyproject.toml | head -1)"
VERSION="${VERSION:-0.1.0}"
cat > "$STAGING/DEBIAN/control" <<EOF
Package: mavix-desktop
Version: $VERSION
Section: net
Priority: optional
Architecture: amd64
Maintainer: Mavix Team <noreply@mavix.invalid>
Description: Mavix Desktop — UAV Ground Control Station
 PC-приёмник для системы дистанционного управления дронами Mavix.
 Принимает видеопоток по WebRTC, шлёт CRSF/MAVLink-команды с
 джойстика, поддерживает QGroundControl для MAVLink-полётников.
EOF

# --root-owner-group чтобы файлы в .deb не несли uid/gid сборочной
# машины (без флага владельцем стал бы текущий $USER).
dpkg-deb --root-owner-group --build "$STAGING" "dist/mavix-desktop-linux.deb"

DEB_PATH="dist/mavix-desktop-linux.deb"
echo ""
echo "OK Сборка готова: $DEB_PATH"
echo "   Установка: sudo dpkg -i $DEB_PATH"
echo "   Скопируйте в MavixWeb/public/downloads/ для раздачи через сайт."
