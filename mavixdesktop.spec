# mavixdesktop.spec — PyInstaller config for a single-file build.
# Usage: pyinstaller mavixdesktop.spec
from PyInstaller.utils.hooks import collect_all

# Приложение чисто на QtWidgets и использует только QtCore/QtGui/QtWidgets/QtSvg.
# collect_all('PySide6') тянет ВЕСЬ Qt, включая огромные неиспользуемые модули:
# QtWebEngine (встроенный Chromium, ~195 МБ), QtQuick/QtQml, Qt3D, QtDesigner,
# QtPdf, QtCharts/QtGraphs, QtMultimedia (+ свой ffmpeg) и т.п. Все они зависят от
# QtGui/QtCore, а не наоборот, поэтому удаление их из бандла безопасно для
# Widgets-приложения. Собираем PySide6 целиком (чтобы точно были платформенные
# плагины), затем выкидываем тяжёлые семейства по подстроке имени — единым
# фильтром по бинарникам, datas и hiddenimports, чтобы PyInstaller не подтянул
# их обратно по зависимостям.
_QT_DROP = (
    'webengine', 'webview', 'icudtl',          # встроенный Chromium — самый жирный кусок
    'quick', 'qml',                            # QML/Quick стек (libQt6Quick, qml/, qmltooling…)
    '3d', 'shadertools',                       # Qt3D / Quick3D / RHI-шейдеры
    'designer',                                # Qt Designer
    'pdf',                                     # QtPdf
    'charts', 'graphs', 'datavisualization',
    'multimedia', 'spatialaudio',             # QtMultimedia (+ его ffmpeg ниже)
    'libavcodec', 'libavformat', 'libavutil',  # ffmpeg внутри Qt (наш PyAV — отдельный пакет av)
    'libavfilter', 'libavdevice', 'libswscale', 'libswresample',
)


def _is_unwanted_qt(name: str) -> bool:
    low = name.lower()
    return any(token in low for token in _QT_DROP)


datas = []
binaries = []
hiddenimports = [
    'aiortc',
    'av',
    'PySide6.QtSvg',
    'PySide6.QtSvgWidgets',
    'pymavlink.dialects.v20.common',
    'pymavlink.dialects.v20.ardupilotmega',
]

# PySide6 — собрать и отфильтровать тяжёлые неиспользуемые модули.
_p_datas, _p_binaries, _p_hidden = collect_all('PySide6')
datas += [(src, dest) for (src, dest) in _p_datas if not _is_unwanted_qt(dest)]
binaries += [(src, dest) for (src, dest) in _p_binaries if not _is_unwanted_qt(dest)]
hiddenimports += [mod for mod in _p_hidden if not _is_unwanted_qt(mod)]

# Остальные пакеты нужны целиком (PyAV/aiortc — видео, pymavlink — протокол FC).
for pkg in ('av', 'aiortc', 'pymavlink'):
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
    # Дублируем исключение неиспользуемых модулей на уровне графа импортов,
    # чтобы PyInstaller не пытался их анализировать/подтягивать обратно.
    excludes=[
        'cv2',
        'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick',
        'PySide6.QtQuick', 'PySide6.QtQuick3D', 'PySide6.QtQuickWidgets', 'PySide6.QtQuickControls2',
        'PySide6.QtQml',
        'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.Qt3DExtras',
        'PySide6.Qt3DInput', 'PySide6.Qt3DLogic', 'PySide6.Qt3DAnimation',
        'PySide6.QtDesigner', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
        'PySide6.QtCharts', 'PySide6.QtGraphs', 'PySide6.QtDataVisualization',
        'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets', 'PySide6.QtSpatialAudio',
    ],
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
