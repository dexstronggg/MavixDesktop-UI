# mavixdesktop.spec — PyInstaller config for a single-file build.
# Usage: pyinstaller mavixdesktop.spec
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = [
    'aiortc',
    'av',
    'cv2',
    'PySide6.QtSvg',
    'PySide6.QtSvgWidgets',
    'PySide6.QtNetwork',
    'pymavlink.dialects.v20.common',
    'pymavlink.dialects.v20.ardupilotmega',
]

for pkg in ('PySide6', 'av', 'aiortc', 'cv2', 'pymavlink'):
    _datas, _binaries, _hidden = collect_all(pkg)
    datas += _datas
    binaries += _binaries
    hiddenimports += _hidden

datas += [('src/mavixdesktop/ui/icons', 'mavixdesktop/ui/icons')]

a = Analysis(
    ['src/mavixdesktop/__main__.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='mavixdesktop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
