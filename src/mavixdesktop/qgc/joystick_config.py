"""Пишет калибровку джойстика в .ini QGroundControl (Stable 5.0.8).

QGC 5.0.8 собран на SDL2 и читает калибровку из «легаси»-раздела
`[Joysticks/<имя>]`: ключи `RollAxis`/`PitchAxis`/`YawAxis`/`ThrottleAxis` —
индексы осей SDL в конвенции Mode 2, `Calibrated4=true` включает готовую
калибровку, `Axis<N>Min/Max/Trim/Rev/Deadbnd` — параметры осей. Формат
`JoystickSettingsV2` из Daily/мастера на 5.0.8 не читается.

Пишем эти ключи тем же классом `QSettings` с `IniFormat`, которым пользуется
сам QGC (на Windows он принудительно выставляет
`QSettings::setDefaultFormat(IniFormat)` и держит файл в
`%APPDATA%\\QGroundControl`), поэтому формат файла совпадает и модуль работает
там же, если `find_qgc_settings_files` смотрит в нужный каталог.
`SDL_GAMECONTROLLERCONFIG` в 5.0.8 **читается** (mavlink/qgroundcontrol#12639):
устройство, опознанное как game controller, требует в `RollAxis` и т.п.
логические индексы осей SDL, а не сырые, — модуль переводит их через нашу
SDL-строку калибровки (`sdl_gamecontrollerconfig`), а для обычного
raw-джойстика пишет сырые индексы.
"""

from __future__ import annotations

import os
import platform
import re
from pathlib import Path

from PySide6.QtCore import QSettings

from mavixdesktop.core.logger import logger

# Логические индексы осей SDL_GameControllerAxis: leftx=0, lefty=1,
# rightx=2, righty=3.
_LOGICAL_AXES: dict[str, int] = {
    'leftx': 0,
    'lefty': 1,
    'rightx': 2,
    'righty': 3,
}

# (ключ оси в калибровке, ключ min, ключ max, имя ключа в [Joysticks/<имя>]).
_AXIS_FUNCTIONS: tuple[tuple[str, str, str, str], ...] = (
    ('axis_roll', 'roll_min', 'roll_max', 'RollAxis'),
    ('axis_pitch', 'pitch_min', 'pitch_max', 'PitchAxis'),
    ('axis_yaw', 'yaw_min', 'yaw_max', 'YawAxis'),
    ('axis_thr', 'thr_min', 'thr_max', 'ThrottleAxis'),
)


def _reversed(calibration: dict[str, object], min_key: str, max_key: str) -> bool:
    """Инверсия оси по диапазону калибровки: максимум даёт меньшее значение."""
    min_v = calibration.get(min_key, -1.0)
    max_v = calibration.get(max_key, 1.0)
    if not isinstance(min_v, (int, float)) or isinstance(min_v, bool):
        return False
    if not isinstance(max_v, (int, float)) or isinstance(max_v, bool):
        return False
    return max_v < min_v


def _logical_index(calibration: dict[str, object], raw_axis: int) -> int | None:
    """Логический индекс оси для game controller по SDL-строке калибровки.

    Строка `sdl_gamecontrollerconfig` отображает логические имена на сырые
    индексы (`leftx:a3,lefty:a2~,...`). Инвертируем её: ищем имя, чей сырой
    индекс равен нашему, и возвращаем его логический номер (leftx=0, lefty=1,
    rightx=2, righty=3). Строки нет или оси в ней нет — это обычный
    raw-джойстик, возвращаем None.
    """
    mapping = calibration.get('sdl_gamecontrollerconfig')
    if not isinstance(mapping, str):
        return None
    raw_to_logical: dict[int, str] = {}
    for part in mapping.split(','):
        match = re.fullmatch(r'([A-Za-z0-9]+):a(-?\d+)[~-]?', part.strip())
        if match:
            raw_to_logical[int(match.group(2))] = match.group(1)
    name = raw_to_logical.get(raw_axis)
    if name is None:
        return None
    return _LOGICAL_AXES.get(name)


def find_qgc_settings_files(config_dir: Path | None = None) -> list[Path]:
    """.ini QGroundControl в каталогах настроек (обычно один — Stable либо Daily).

    Linux/macOS: `~/.config` (или `$XDG_CONFIG_HOME`, если задан); на macOS
    дополнительно `~/Library/Preferences`. Windows: `%APPDATA%` (запасной —
    `~/.config`).
    """
    if config_dir is not None:
        roots = [config_dir]
    else:
        system = platform.system()
        if system == 'Windows':
            appdata = os.environ.get('APPDATA')
            roots = [Path(appdata) if appdata else Path.home() / '.config']
        else:
            xdg = os.environ.get('XDG_CONFIG_HOME')
            roots = [Path(xdg) if xdg else Path.home() / '.config']
            if system == 'Darwin':
                roots.append(Path.home() / 'Library' / 'Preferences')
    return sorted(
        {
            p
            for root in roots
            for p in root.glob('QGroundControl*/QGroundControl*.ini')
            if p.is_file()
        }
    )


def apply_calibration(
    calibration: dict[str, object], joystick_name: str, ini_path: Path
) -> bool:
    """Пишет назначение осей в легаси-раздел `[Joysticks/<имя>]` одного .ini.

    `RollAxis` и остальные — индекс оси SDL (сырой, либо логический для
    game controller). Точные min/max/trim/deadband, заданные пилотом в самом
    QGC, не затираем — для осей, остающихся в работе, сохраняем их цифры.
    """
    try:
        qsettings = QSettings(str(ini_path), QSettings.Format.IniFormat)
        prefix = f'Joysticks/{joystick_name}'

        planned: list[tuple[int, bool, str]] = []
        axes: list[int] = []
        for axis_key, min_key, max_key, function_key in _AXIS_FUNCTIONS:
            raw_axis = calibration.get(axis_key)
            if not isinstance(raw_axis, int) or isinstance(raw_axis, bool):
                continue
            logical = _logical_index(calibration, raw_axis)
            index = logical if logical is not None else raw_axis
            planned.append(
                (index, _reversed(calibration, min_key, max_key), function_key)
            )
            axes.append(index)

        # точные значения оси (диапазон/trim/мёртвая зона) пилот мог задать
        # в самом QGC — для остающихся в работе осей сохраняем его цифры
        keep = {
            axis: {
                field: qsettings.value(f'{prefix}/Axis{axis}{field}')
                for field in ('Min', 'Max', 'Trim', 'Rev', 'Deadbnd')
            }
            for axis in axes
        }

        for axis, reversed_, function_key in planned:
            qsettings.setValue(f'{prefix}/{function_key}', axis)
            fields = {
                'Min': -32768,
                'Max': 32767,
                'Trim': 0,
                'Rev': reversed_,
                'Deadbnd': 0,
            }
            for field, default in fields.items():
                saved = keep[axis][field]
                qsettings.setValue(
                    f'{prefix}/Axis{axis}{field}', default if saved is None else saved
                )

        qsettings.setValue(f'{prefix}/Calibrated4', True)
        # режим трансмиттера — глобальный для типа ЛА в [Joysticks]; калибровку
        # пишем в конвенции Mode 2, поэтому фиксируем TXMode_MultiRotor=2
        qsettings.setValue('Joysticks/TXMode_MultiRotor', 2)
        qsettings.setValue('JoystickManager/ActiveJoystick', joystick_name)

        qsettings.sync()
        return qsettings.status() == QSettings.Status.NoError
    except Exception as exc:
        logger.warning(
            '[qgc] не удалось записать калибровку джойстика в %s: %s', ini_path, exc
        )
        return False


def apply_calibration_to_all(calibration: dict[str, object], joystick_name: str) -> int:
    """Пишет калибровку во все найденные .ini QGC. Возвращает число успешных."""
    files = find_qgc_settings_files()
    if not files:
        logger.info(
            '[qgc] .ini QGroundControl не найден (первый запуск?) — '
            'калибровка джойстика не записана, QGC придётся настроить вручную'
        )
        return 0
    applied = sum(
        1 for path in files if apply_calibration(calibration, joystick_name, path)
    )
    logger.info('[qgc] калибровка джойстика записана в %d/%d .ini', applied, len(files))
    return applied
