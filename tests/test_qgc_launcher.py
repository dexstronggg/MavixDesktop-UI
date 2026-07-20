from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mavixdesktop.qgc import launcher


def test_find_qgc_returns_none_on_unsupported_platform(monkeypatch):
    monkeypatch.setattr('mavixdesktop.qgc.launcher.platform.system', lambda: 'FreeBSD')
    assert launcher.find_qgc() is None


def test_find_qgc_uses_path_on_linux(monkeypatch, tmp_path):
    fake = tmp_path / 'QGroundControl'
    fake.write_text('binary')
    monkeypatch.setattr('mavixdesktop.qgc.launcher.platform.system', lambda: 'Linux')
    monkeypatch.setattr('mavixdesktop.qgc.launcher.shutil.which',
                        lambda name: str(fake) if name == 'QGroundControl' else None)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    result = launcher.find_qgc()
    assert result == fake


def test_is_qgc_running_true_when_shm_attached(monkeypatch):
    fake_shm = MagicMock()
    fake_shm.attach.return_value = True
    monkeypatch.setattr('PySide6.QtCore.QSharedMemory', lambda key: fake_shm)
    assert launcher.is_qgc_running() is True
    fake_shm.detach.assert_called_once()


def test_is_qgc_running_false_when_shm_missing(monkeypatch):
    fake_shm = MagicMock()
    fake_shm.attach.return_value = False
    monkeypatch.setattr('PySide6.QtCore.QSharedMemory', lambda key: fake_shm)
    assert launcher.is_qgc_running() is False


def test_launch_qgc_returns_none_when_not_found(monkeypatch):
    monkeypatch.setattr('mavixdesktop.qgc.launcher.find_qgc', lambda: None)
    assert launcher.launch_qgc() is None


def test_launch_qgc_sets_sdl_env(monkeypatch, tmp_path):
    fake = tmp_path / 'qgc'
    fake.write_text('#!/bin/sh\necho ok\n')
    fake.chmod(0o755)
    monkeypatch.setattr('mavixdesktop.qgc.launcher.find_qgc', lambda: fake)

    popen_seen = {}

    class FakePopen:
        def __init__(self, args, env=None, **kw):
            popen_seen['args'] = args
            popen_seen['env'] = env
            self.pid = 4242

    monkeypatch.setattr('mavixdesktop.qgc.launcher.subprocess.Popen', FakePopen)
    proc = launcher.launch_qgc('test-sdl-config')
    assert proc is not None
    assert popen_seen['env'].get('SDL_GAMECONTROLLERCONFIG') == 'test-sdl-config'
    assert popen_seen['args'][0] == str(fake)


def test_launch_qgc_handles_popen_error(monkeypatch, tmp_path):
    fake = tmp_path / 'qgc'
    fake.write_text('x')
    monkeypatch.setattr('mavixdesktop.qgc.launcher.find_qgc', lambda: fake)
    monkeypatch.setattr('mavixdesktop.qgc.launcher.subprocess.Popen',
                        MagicMock(side_effect=OSError('exec')))
    assert launcher.launch_qgc() is None


# ── точное распознавание исполняемого файла (не инсталлятора) ───────────────────
def test_is_qgc_windows_exe_matches_only_exact():
    assert launcher._is_qgc_windows_exe('QGroundControl.exe') is True
    assert launcher._is_qgc_windows_exe('qgroundcontrol.exe') is True
    # инсталлятор и деинсталлятор не должны опознаваться как приложение
    assert launcher._is_qgc_windows_exe('QGroundControl-installer-AMD64.exe') is False
    assert launcher._is_qgc_windows_exe('unins000.exe') is False


def test_is_qgc_linux_file_matches_binary_and_appimage():
    assert launcher._is_qgc_linux_file('QGroundControl') is True
    assert launcher._is_qgc_linux_file('QGroundControl-x86_64.AppImage') is True
    assert launcher._is_qgc_linux_file('qgroundcontrol-aarch64.appimage') is True
    # установочный .exe/прочее под Linux-предикат не подходит
    assert launcher._is_qgc_linux_file('QGroundControl-installer.exe') is False


# ── ограниченный поиск: глубина и точное имя ───────────────────────────────────
def test_bounded_find_respects_depth_limit(tmp_path, monkeypatch):
    # файл лежит глубже _SEARCH_MAX_DEPTH — не должен найтись
    monkeypatch.setattr(launcher, '_SEARCH_MAX_DEPTH', 1)
    deep = tmp_path / 'a' / 'b' / 'c'
    deep.mkdir(parents=True)
    (deep / 'QGroundControl.exe').write_text('x')
    found = launcher._bounded_find([tmp_path], launcher._is_qgc_windows_exe, 5.0)
    assert found is None


def test_bounded_find_finds_within_depth(tmp_path):
    target = tmp_path / 'sub' / 'QGroundControl.exe'
    target.parent.mkdir(parents=True)
    target.write_text('x')
    found = launcher._bounded_find([tmp_path], launcher._is_qgc_windows_exe, 5.0)
    assert found == target


def test_bounded_find_ignores_installer(tmp_path):
    (tmp_path / 'QGroundControl-installer-AMD64.exe').write_text('x')
    found = launcher._bounded_find([tmp_path], launcher._is_qgc_windows_exe, 5.0)
    assert found is None


# ── авто-сохранение найденного пути ────────────────────────────────────────────
def test_find_qgc_saves_found_path(tmp_path, monkeypatch):
    store = tmp_path / 'qgc_path.txt'
    monkeypatch.setattr(launcher, '_QGC_PATH_FILE', store)
    found = tmp_path / 'opt' / 'QGroundControl.exe'
    found.parent.mkdir(parents=True)
    found.write_text('x')
    monkeypatch.setattr('mavixdesktop.qgc.launcher.platform.system', lambda: 'Windows')
    monkeypatch.setattr('mavixdesktop.qgc.launcher.shutil.which', lambda name: None)
    monkeypatch.setattr(launcher, '_find_qgc_windows', lambda deadline_s: found)
    result = launcher.find_qgc()
    assert result == found
    assert store.read_text(encoding='utf-8').strip() == str(found)
    # повторный вызов читает сохранённый путь, поиск не запускается
    monkeypatch.setattr(launcher, '_find_qgc_windows',
                        lambda deadline_s: (_ for _ in ()).throw(AssertionError('не должен искать')))
    assert launcher.find_qgc() == found


# ── явный путь не запускает поиск ──────────────────────────────────────────────
def test_launch_qgc_with_explicit_path_skips_search(monkeypatch, tmp_path):
    fake = tmp_path / 'QGroundControl.exe'
    fake.write_text('x')
    monkeypatch.setattr('mavixdesktop.qgc.launcher.find_qgc',
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError('не должен искать')))
    seen = {}

    class FakePopen:
        def __init__(self, args, env=None, **kw):
            seen['args'] = args
            self.pid = 7

    monkeypatch.setattr('mavixdesktop.qgc.launcher.subprocess.Popen', FakePopen)
    proc = launcher.launch_qgc('cfg', qgc_path=fake)
    assert proc is not None
    assert seen['args'][0] == str(fake)
