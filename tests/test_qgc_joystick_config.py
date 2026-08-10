"""apply_calibration: legacy-калибровка джойстика пишется в .ini QGC тем же QSettings."""

from __future__ import annotations

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QSettings

from mavixdesktop.qgc.joystick_config import (
    apply_calibration,
    apply_calibration_to_all,
    find_qgc_settings_files,
)

NAME = 'EdgeTX Radiomaster Pocket Joystick'


def _cal(**overrides):
    base = {
        'axis_roll': 0,
        'axis_pitch': 1,
        'axis_yaw': 2,
        'axis_thr': 4,
        'roll_min': -1.0,
        'roll_max': 1.0,
        'pitch_min': -1.0,
        'pitch_max': 1.0,
        'yaw_min': -1.0,
        'yaw_max': 1.0,
        'thr_min': 1.0,
        'thr_max': -1.0,  # инвертирован: физический максимум даёт меньшее значение
    }
    base.update(overrides)
    return base


def test_writes_axis_assignment_and_reversed_for_each_axis(tmp_path):
    ini = tmp_path / 'QGroundControl.ini'
    assert apply_calibration(_cal(), NAME, ini)

    q = QSettings(str(ini), QSettings.Format.IniFormat)
    prefix = f'Joysticks/{NAME}'
    assert q.value(f'{prefix}/RollAxis') == 0
    assert q.value(f'{prefix}/PitchAxis') == 1
    assert q.value(f'{prefix}/YawAxis') == 2
    assert q.value(f'{prefix}/ThrottleAxis') == 4
    assert q.value(f'{prefix}/Axis4Rev') in (True, 'true')
    assert q.value(f'{prefix}/Axis0Rev') in (False, 'false')


def test_sets_calibrated_and_active_joystick(tmp_path):
    ini = tmp_path / 'QGroundControl.ini'
    apply_calibration(_cal(), NAME, ini)

    q = QSettings(str(ini), QSettings.Format.IniFormat)
    prefix = f'Joysticks/{NAME}'
    assert q.value(f'{prefix}/Calibrated4') in (True, 'true')
    assert q.value('JoystickManager/ActiveJoystick') == NAME


def test_pins_global_tx_mode_2(tmp_path):
    """QGC хранит назначение осей в конвенции Mode 2, а раскладку по режимам
    берёт из глобального TXMode_MultiRotor — фиксируем 2."""
    ini = tmp_path / 'QGroundControl.ini'
    apply_calibration(_cal(), NAME, ini)

    q = QSettings(str(ini), QSettings.Format.IniFormat)
    assert q.value('Joysticks/TXMode_MultiRotor') == 2


def test_overrides_tx_mode_to_2_even_if_something_else_was_set(tmp_path):
    ini = tmp_path / 'QGroundControl.ini'
    q = QSettings(str(ini), QSettings.Format.IniFormat)
    q.setValue('Joysticks/TXMode_MultiRotor', 1)
    q.sync()

    apply_calibration(_cal(), NAME, ini)

    q2 = QSettings(str(ini), QSettings.Format.IniFormat)
    assert q2.value('Joysticks/TXMode_MultiRotor') == 2


def test_fills_full_range_when_axis_never_calibrated_before(tmp_path):
    ini = tmp_path / 'QGroundControl.ini'
    apply_calibration(_cal(), NAME, ini)

    q = QSettings(str(ini), QSettings.Format.IniFormat)
    prefix = f'Joysticks/{NAME}'
    assert q.value(f'{prefix}/Axis0Min') == -32768
    assert q.value(f'{prefix}/Axis0Max') == 32767
    assert q.value(f'{prefix}/Axis0Trim') == 0
    assert q.value(f'{prefix}/Axis0Deadbnd') == 0


def test_preserves_existing_calibration_done_inside_qgc(tmp_path):
    """Если пилот уже откалибровал ось прямо в QGC — не затирать его цифры."""
    ini = tmp_path / 'QGroundControl.ini'
    prefix = f'Joysticks/{NAME}'
    q = QSettings(str(ini), QSettings.Format.IniFormat)
    q.setValue(f'{prefix}/Axis4Min', -32768)
    q.setValue(f'{prefix}/Axis4Max', 32767)
    q.setValue(f'{prefix}/Axis4Trim', -1)
    q.setValue(f'{prefix}/Axis4Deadbnd', 13106)
    q.sync()

    apply_calibration(_cal(), NAME, ini)

    q2 = QSettings(str(ini), QSettings.Format.IniFormat)
    assert q2.value(f'{prefix}/Axis4Deadbnd') == 13106
    assert q2.value(f'{prefix}/Axis4Trim') == -1


def test_keeps_fine_calibration_of_an_axis_that_stays_in_use(tmp_path):
    """Ось 4 — газ и в старой, и в новой раскладке: trim/deadband из QGC не теряем."""
    ini = tmp_path / 'QGroundControl.ini'
    prefix = f'Joysticks/{NAME}'
    q = QSettings(str(ini), QSettings.Format.IniFormat)
    q.setValue(f'{prefix}/Axis4Trim', -1)
    q.setValue(f'{prefix}/Axis4Deadbnd', 13106)
    q.sync()

    apply_calibration(_cal(axis_thr=4), NAME, ini)

    q2 = QSettings(str(ini), QSettings.Format.IniFormat)
    assert q2.value(f'{prefix}/Axis4Deadbnd') == 13106
    assert q2.value(f'{prefix}/Axis4Trim') == -1
    assert q2.value(f'{prefix}/ThrottleAxis') == 4


def test_ignores_non_integer_axis_index_but_still_succeeds(tmp_path):
    ini = tmp_path / 'QGroundControl.ini'
    assert apply_calibration({'axis_roll': 'oops'}, NAME, ini) is True

    q = QSettings(str(ini), QSettings.Format.IniFormat)
    prefix = f'Joysticks/{NAME}'
    assert not q.contains(f'{prefix}/RollAxis')
    assert q.value(f'{prefix}/Calibrated4') in (True, 'true')


def test_never_writes_v2_keys(tmp_path):
    """5.0.8 читает только legacy-раздел [Joysticks/<имя>] — V2-ключи не пишем."""
    ini = tmp_path / 'QGroundControl.ini'
    apply_calibration(_cal(), NAME, ini)

    q = QSettings(str(ini), QSettings.Format.IniFormat)
    assert not q.contains(f'JoystickSettingsV2/{NAME}/calibrated')
    assert not q.contains(f'JoystickSettingsV2/{NAME}/transmitterMode')
    assert not q.contains('JoystickManager/activeJoystickName')


def test_translates_to_logical_indices_for_game_controller(tmp_path):
    """Устройство, опознанное как game controller, требует логические индексы
    SDL: по нашей SDL-строке leftx=0, lefty=1, rightx=2, righty=3."""
    ini = tmp_path / 'QGroundControl.ini'
    sdl = (
        '03000000ff110000413300004f150000,'
        'EdgeTX Radiomaster Pocket Joystick,'
        'leftx:a3,lefty:a2~,rightx:a0,righty:a1~,a:b4,platform:Linux'
    )
    cal = _cal(
        axis_roll=0, axis_pitch=1, axis_yaw=3, axis_thr=2, sdl_gamecontrollerconfig=sdl
    )
    assert apply_calibration(cal, NAME, ini)

    q = QSettings(str(ini), QSettings.Format.IniFormat)
    prefix = f'Joysticks/{NAME}'
    assert q.value(f'{prefix}/RollAxis') == 2  # rightx (raw 0)
    assert q.value(f'{prefix}/PitchAxis') == 3  # righty (raw 1)
    assert q.value(f'{prefix}/YawAxis') == 0  # leftx (raw 3)
    assert q.value(f'{prefix}/ThrottleAxis') == 1  # lefty (raw 2)
    assert q.value(f'{prefix}/Axis1Rev') in (True, 'true')  # газ инвертирован
    assert q.value(f'{prefix}/Axis2Rev') in (False, 'false')  # крен прямой


def test_falls_back_to_raw_index_when_axis_missing_from_mapping(tmp_path):
    """Ось, которой нет в SDL-строке, — обычный raw-джойстик: пишем сырой индекс."""
    ini = tmp_path / 'QGroundControl.ini'
    sdl = 'GUID,Name,leftx:a0,lefty:a1,rightx:a2,righty:a3,platform:Linux'
    cal = _cal(axis_thr=5, sdl_gamecontrollerconfig=sdl)
    assert apply_calibration(cal, NAME, ini)

    q = QSettings(str(ini), QSettings.Format.IniFormat)
    prefix = f'Joysticks/{NAME}'
    assert q.value(f'{prefix}/ThrottleAxis') == 5
    assert q.value(f'{prefix}/RollAxis') == 0  # leftx (raw 0)
    assert q.value(f'{prefix}/PitchAxis') == 1  # lefty (raw 1)
    assert q.value(f'{prefix}/YawAxis') == 2  # rightx (raw 2)


def test_falls_back_to_raw_index_without_mapping(tmp_path):
    """Без SDL-строки (raw-джойстик) пишем сырые индексы pygame."""
    ini = tmp_path / 'QGroundControl.ini'
    apply_calibration(_cal(), NAME, ini)

    q = QSettings(str(ini), QSettings.Format.IniFormat)
    prefix = f'Joysticks/{NAME}'
    assert q.value(f'{prefix}/RollAxis') == 0
    assert q.value(f'{prefix}/ThrottleAxis') == 4


def test_find_settings_files_matches_stable_and_daily(tmp_path):
    (tmp_path / 'QGroundControl').mkdir()
    (tmp_path / 'QGroundControl' / 'QGroundControl.ini').touch()
    (tmp_path / 'QGroundControl Daily').mkdir()
    (tmp_path / 'QGroundControl Daily' / 'QGroundControl Daily.ini').touch()
    (tmp_path / 'QGroundControl').joinpath('unrelated.txt').touch()

    found = find_qgc_settings_files(tmp_path)
    assert len(found) == 2
    assert all(p.suffix == '.ini' for p in found)


def test_find_settings_files_empty_when_qgc_never_ran(tmp_path):
    assert find_qgc_settings_files(tmp_path) == []


def test_find_settings_files_honors_xdg_config_home(tmp_path, monkeypatch):
    monkeypatch.setattr(
        'mavixdesktop.qgc.joystick_config.platform.system', lambda: 'Linux'
    )
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    target = tmp_path / 'QGroundControl' / 'QGroundControl.ini'
    target.parent.mkdir(parents=True)
    target.touch()

    assert find_qgc_settings_files() == [target]


def test_find_settings_files_windows_uses_appdata(tmp_path, monkeypatch):
    monkeypatch.setattr(
        'mavixdesktop.qgc.joystick_config.platform.system', lambda: 'Windows'
    )
    monkeypatch.setenv('APPDATA', str(tmp_path))
    target = tmp_path / 'QGroundControl' / 'QGroundControl.ini'
    target.parent.mkdir(parents=True)
    target.touch()

    assert find_qgc_settings_files() == [target]


def test_find_settings_files_windows_falls_back_to_home_config(tmp_path, monkeypatch):
    monkeypatch.setattr(
        'mavixdesktop.qgc.joystick_config.platform.system', lambda: 'Windows'
    )
    monkeypatch.delenv('APPDATA', raising=False)
    monkeypatch.setattr('mavixdesktop.qgc.joystick_config.Path.home', lambda: tmp_path)
    target = tmp_path / '.config' / 'QGroundControl' / 'QGroundControl.ini'
    target.parent.mkdir(parents=True)
    target.touch()

    assert find_qgc_settings_files() == [target]


def test_find_settings_files_macos_includes_library_preferences(tmp_path, monkeypatch):
    monkeypatch.setattr(
        'mavixdesktop.qgc.joystick_config.platform.system', lambda: 'Darwin'
    )
    monkeypatch.delenv('XDG_CONFIG_HOME', raising=False)
    monkeypatch.setattr('mavixdesktop.qgc.joystick_config.Path.home', lambda: tmp_path)
    config = tmp_path / '.config' / 'QGroundControl' / 'QGroundControl.ini'
    config.parent.mkdir(parents=True)
    config.touch()
    prefs = (
        tmp_path / 'Library' / 'Preferences' / 'QGroundControl' / 'QGroundControl.ini'
    )
    prefs.parent.mkdir(parents=True)
    prefs.touch()

    assert find_qgc_settings_files() == [config, prefs]


def test_apply_to_all_reports_zero_without_any_ini(tmp_path, monkeypatch):
    monkeypatch.setattr(
        'mavixdesktop.qgc.joystick_config.find_qgc_settings_files', lambda: []
    )
    assert apply_calibration_to_all(_cal(), NAME) == 0


def test_apply_to_all_writes_to_every_found_ini(tmp_path, monkeypatch):
    files = [tmp_path / 'a.ini', tmp_path / 'b.ini']
    monkeypatch.setattr(
        'mavixdesktop.qgc.joystick_config.find_qgc_settings_files', lambda: files
    )
    assert apply_calibration_to_all(_cal(), NAME) == 2
    for f in files:
        assert f.exists()
