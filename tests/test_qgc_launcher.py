from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mavixdesktop.core import user_config
from mavixdesktop.qgc import launcher


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch, tmp_path):
    monkeypatch.setattr(user_config, 'USER_CONFIG_PATH', tmp_path / 'config.json')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)


def test_save_and_get_qgc_path_roundtrip(tmp_path) -> None:
    fake = tmp_path / 'QGroundControl'
    fake.write_text('binary')
    launcher.save_qgc_path(fake)
    assert user_config.load()['qgc_path'] == str(fake)
    assert launcher.get_saved_qgc_path() == fake


def test_get_saved_qgc_path_clears_stale_path(tmp_path) -> None:
    missing = tmp_path / 'gone' / 'QGroundControl'
    user_config.save({'qgc_path': str(missing)})
    assert launcher.get_saved_qgc_path() is None
    assert 'qgc_path' not in user_config.load()


def test_clear_keeps_other_keys(tmp_path) -> None:
    user_config.save({'qgc_path': '/x', 'signal_url': 'http://h'})
    launcher.clear_saved_qgc_path()
    data = user_config.load()
    assert 'qgc_path' not in data
    assert data['signal_url'] == 'http://h'


def test_migrates_legacy_txt_path(tmp_path) -> None:
    fake = tmp_path / 'QGroundControl'
    fake.write_text('binary')
    legacy = launcher._legacy_path_file()
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(str(fake), encoding='utf-8')

    assert launcher.get_saved_qgc_path() == fake
    assert user_config.load()['qgc_path'] == str(fake)
    assert not legacy.exists()


def test_find_qgc_returns_none_on_unsupported_platform(monkeypatch) -> None:
    monkeypatch.setattr('mavixdesktop.qgc.launcher.platform.system', lambda: 'FreeBSD')
    assert launcher.find_qgc() is None


def test_find_qgc_prefers_saved_path(tmp_path, monkeypatch) -> None:
    fake = tmp_path / 'QGroundControl'
    fake.write_text('binary')
    launcher.save_qgc_path(fake)
    monkeypatch.setattr('mavixdesktop.qgc.launcher.platform.system', lambda: 'Linux')
    monkeypatch.setattr('mavixdesktop.qgc.launcher._find_qgc_linux',
                        lambda *a: pytest.fail('search should not run'))
    assert launcher.find_qgc() == fake


def test_find_qgc_uses_path_on_linux_and_saves(monkeypatch, tmp_path) -> None:
    fake = tmp_path / 'QGroundControl'
    fake.write_text('binary')
    monkeypatch.setattr('mavixdesktop.qgc.launcher.platform.system', lambda: 'Linux')
    monkeypatch.setattr('mavixdesktop.qgc.launcher.shutil.which',
                        lambda name: str(fake) if name == 'QGroundControl' else None)
    result = launcher.find_qgc()
    assert result == fake
    assert user_config.load()['qgc_path'] == str(fake)


def test_windows_predicate_matches_only_app_exe() -> None:
    assert launcher._is_qgc_windows_exe('QGroundControl.exe')
    assert launcher._is_qgc_windows_exe('qgroundcontrol.exe')
    assert not launcher._is_qgc_windows_exe('QGroundControl-installer-AMD64.exe')
    assert not launcher._is_qgc_windows_exe('unins000.exe')
    assert not launcher._is_qgc_windows_exe('QGroundControl.AppImage')


def test_linux_predicate_matches_binary_and_appimage() -> None:
    assert launcher._is_qgc_linux_file('QGroundControl')
    assert launcher._is_qgc_linux_file('QGroundControl-x86_64.AppImage')
    assert launcher._is_qgc_linux_file('QGroundControl-aarch64.AppImage')
    assert not launcher._is_qgc_linux_file('QGroundControl-installer.run')
    assert not launcher._is_qgc_linux_file('something-else')


def test_bounded_find_ignores_installer_picks_app(tmp_path) -> None:
    (tmp_path / 'QGroundControl-installer-AMD64.exe').write_text('x')
    (tmp_path / 'QGroundControl.exe').write_text('x')
    found = launcher._bounded_find([tmp_path], launcher._is_qgc_windows_exe, 5.0)
    assert found == tmp_path / 'QGroundControl.exe'


def test_bounded_find_respects_depth(tmp_path) -> None:
    shallow = tmp_path / 'sub'
    shallow.mkdir()
    (shallow / 'QGroundControl').write_text('x')
    found = launcher._bounded_find([tmp_path], launcher._is_qgc_linux_file, 5.0)
    assert found == shallow / 'QGroundControl'


def test_bounded_find_skips_too_deep(tmp_path) -> None:
    deep = tmp_path / 'd1' / 'd2' / 'd3'
    deep.mkdir(parents=True)
    (deep / 'QGroundControl').write_text('x')
    found = launcher._bounded_find([tmp_path], launcher._is_qgc_linux_file, 5.0)
    assert found is None


def test_bounded_find_stops_on_deadline(tmp_path, monkeypatch) -> None:
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'QGroundControl').write_text('x')
    found = launcher._bounded_find([tmp_path], launcher._is_qgc_linux_file, -1.0)
    assert found is None


def test_is_qgc_running_true_when_shm_attached(monkeypatch) -> None:
    fake_shm = MagicMock()
    fake_shm.attach.return_value = True
    monkeypatch.setattr('PySide6.QtCore.QSharedMemory', lambda key: fake_shm)
    assert launcher.is_qgc_running() is True
    fake_shm.detach.assert_called_once()


def test_is_qgc_running_false_when_shm_missing(monkeypatch) -> None:
    fake_shm = MagicMock()
    fake_shm.attach.return_value = False
    monkeypatch.setattr('PySide6.QtCore.QSharedMemory', lambda key: fake_shm)
    assert launcher.is_qgc_running() is False


def test_launch_qgc_returns_none_when_not_found(monkeypatch) -> None:
    monkeypatch.setattr('mavixdesktop.qgc.launcher.find_qgc', lambda: None)
    assert launcher.launch_qgc() is None


def test_launch_qgc_uses_explicit_path(monkeypatch, tmp_path) -> None:
    fake = tmp_path / 'qgc'
    fake.write_text('#!/bin/sh\necho ok\n')
    fake.chmod(0o755)
    monkeypatch.setattr('mavixdesktop.qgc.launcher.find_qgc',
                        lambda *a: pytest.fail('find_qgc should not be called'))

    popen_seen = {}

    class FakePopen:
        def __init__(self, args, env=None, **kw):
            popen_seen['args'] = args
            popen_seen['env'] = env
            self.pid = 4242

    monkeypatch.setattr('mavixdesktop.qgc.launcher.subprocess.Popen', FakePopen)
    proc = launcher.launch_qgc('test-sdl-config', qgc_path=fake)
    assert proc is not None
    assert popen_seen['env'].get('SDL_GAMECONTROLLERCONFIG') == 'test-sdl-config'
    assert popen_seen['args'][0] == str(fake)


def test_launch_qgc_sets_sdl_env_via_find(monkeypatch, tmp_path) -> None:
    fake = tmp_path / 'qgc'
    fake.write_text('#!/bin/sh\necho ok\n')
    fake.chmod(0o755)
    monkeypatch.setattr('mavixdesktop.qgc.launcher.find_qgc', lambda: fake)

    popen_seen = {}

    class FakePopen:
        def __init__(self, args, env=None, **kw):
            popen_seen['env'] = env
            self.pid = 4242

    monkeypatch.setattr('mavixdesktop.qgc.launcher.subprocess.Popen', FakePopen)
    proc = launcher.launch_qgc('test-sdl-config')
    assert proc is not None
    assert popen_seen['env'].get('SDL_GAMECONTROLLERCONFIG') == 'test-sdl-config'


def test_launch_qgc_handles_popen_error(monkeypatch, tmp_path) -> None:
    fake = tmp_path / 'qgc'
    fake.write_text('x')
    monkeypatch.setattr('mavixdesktop.qgc.launcher.subprocess.Popen',
                        MagicMock(side_effect=OSError('exec')))
    assert launcher.launch_qgc(qgc_path=fake) is None
