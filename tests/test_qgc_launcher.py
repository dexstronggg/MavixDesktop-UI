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
