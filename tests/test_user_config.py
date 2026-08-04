"""UI scale stored in ~/.config/mavixdesktop/config.json and applied via QT_SCALE_FACTOR."""
from __future__ import annotations

import json
import os

import pytest

from mavixdesktop.core import user_config


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / 'config.json'
    monkeypatch.setattr(user_config, 'USER_CONFIG_PATH', path)
    return path


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv('QT_SCALE_FACTOR', raising=False)
    yield os.environ
    os.environ.pop('QT_SCALE_FACTOR', None)


def _write(path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding='utf-8')


def test_ui_scale_defaults_when_no_config(config_path):
    assert user_config.load_ui_scale() == user_config.UI_SCALE_DEFAULT


def test_ui_scale_read_from_config(config_path):
    _write(config_path, {'ui_scale': 120})
    assert user_config.load_ui_scale() == 120


def test_ui_scale_clamped_to_max(config_path):
    _write(config_path, {'ui_scale': 400})
    assert user_config.load_ui_scale() == user_config.UI_SCALE_MAX


def test_ui_scale_clamped_to_min(config_path):
    _write(config_path, {'ui_scale': 10})
    assert user_config.load_ui_scale() == user_config.UI_SCALE_MIN


@pytest.mark.parametrize('raw', ['abc', None, [], {}])
def test_ui_scale_falls_back_on_garbage(config_path, raw):
    _write(config_path, {'ui_scale': raw})
    assert user_config.load_ui_scale() == user_config.UI_SCALE_DEFAULT


def test_apply_sets_qt_scale_factor(config_path, clean_env):
    _write(config_path, {'ui_scale': 130})
    user_config.apply_ui_scale_to_env()
    assert clean_env['QT_SCALE_FACTOR'] == '1.30'


def test_apply_skips_when_default(config_path, clean_env):
    _write(config_path, {'ui_scale': user_config.UI_SCALE_DEFAULT})
    user_config.apply_ui_scale_to_env()
    assert 'QT_SCALE_FACTOR' not in clean_env


def test_apply_does_not_override_explicit_env(config_path, monkeypatch):
    monkeypatch.setenv('QT_SCALE_FACTOR', '2.0')
    _write(config_path, {'ui_scale': 130})
    user_config.apply_ui_scale_to_env()
    assert os.environ['QT_SCALE_FACTOR'] == '2.0'
