from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

from mavixdesktop.server import token_store


@pytest.fixture
def isolated_config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr('mavixdesktop.server.token_store.settings.config_dir', tmp_path)
    return tmp_path


@pytest.fixture
def no_keyring(monkeypatch):
    """Force the fallback file path by making keyring import fail."""
    monkeypatch.setattr('mavixdesktop.server.token_store._keyring', lambda: None)


def test_save_then_load_via_file(isolated_config_dir, no_keyring):
    token_store.save('me@example.com', 'r-token-123')
    email, refresh = token_store.load()
    assert email == 'me@example.com'
    assert refresh == 'r-token-123'


def test_load_returns_none_when_empty(isolated_config_dir, no_keyring):
    email, refresh = token_store.load()
    assert email is None
    assert refresh is None


def test_clear_removes_file(isolated_config_dir, no_keyring):
    token_store.save('me@e.c', 'r')
    token_store.clear()
    email, refresh = token_store.load()
    assert email is None
    assert refresh is None


def test_load_handles_corrupt_file(isolated_config_dir, no_keyring):
    p = isolated_config_dir / 'tokens.json'
    p.write_text('not-json{{')
    email, refresh = token_store.load()
    assert email is None
    assert refresh is None


def test_save_via_keyring(isolated_config_dir, monkeypatch):
    kr = MagicMock()
    monkeypatch.setattr('mavixdesktop.server.token_store._keyring', lambda: kr)
    token_store.save('a@b.c', 'r-xyz')
    assert kr.set_password.call_count == 2
    calls = {call.args[1]: call.args[2] for call in kr.set_password.call_args_list}
    assert calls['refresh_token'] == 'r-xyz'
    assert calls['email'] == 'a@b.c'


def test_load_via_keyring(isolated_config_dir, monkeypatch):
    kr = MagicMock()
    kr.get_password.side_effect = lambda svc, key: 'a@b.c' if key == 'email' else 'r-xyz'
    monkeypatch.setattr('mavixdesktop.server.token_store._keyring', lambda: kr)
    email, refresh = token_store.load()
    assert email == 'a@b.c'
    assert refresh == 'r-xyz'


def test_load_falls_back_to_file_if_keyring_raises(isolated_config_dir, monkeypatch):
    p = isolated_config_dir / 'tokens.json'
    import json
    p.write_text(json.dumps({'email': 'file@e.c', 'refresh_token': 'r-file'}))
    kr = MagicMock()
    kr.get_password.side_effect = RuntimeError('locked')
    monkeypatch.setattr('mavixdesktop.server.token_store._keyring', lambda: kr)
    email, refresh = token_store.load()
    assert email == 'file@e.c'
    assert refresh == 'r-file'


def test_save_falls_back_to_file_if_keyring_raises(isolated_config_dir, monkeypatch):
    kr = MagicMock()
    kr.set_password.side_effect = RuntimeError('locked')
    monkeypatch.setattr('mavixdesktop.server.token_store._keyring', lambda: kr)
    token_store.save('a@b.c', 'r-xyz')
    # And reading back without keyring (because we fell back) should still work
    monkeypatch.setattr('mavixdesktop.server.token_store._keyring', lambda: None)
    email, refresh = token_store.load()
    assert email == 'a@b.c'
    assert refresh == 'r-xyz'


# ---------- file-mode tests ----------
# The refresh token is a long-lived credential; the fallback file must
# be owner-only readable. These tests guard against regressions in the
# permission-setting logic.

def test_fallback_file_has_mode_0600(isolated_config_dir, no_keyring):
    token_store.save('a@b.c', 'r-xyz')
    p = isolated_config_dir / 'tokens.json'
    mode = p.stat().st_mode & 0o777
    assert mode == 0o600, f'expected 0o600, got {oct(mode)}'


def test_fallback_overwrites_loose_permissions(isolated_config_dir, no_keyring):
    """A pre-existing file at 0644 must be tightened on the next save."""
    p = isolated_config_dir / 'tokens.json'
    p.write_text('{}')
    os.chmod(p, 0o644)
    assert p.stat().st_mode & 0o777 == 0o644

    token_store.save('a@b.c', 'r-xyz')
    assert p.stat().st_mode & 0o777 == 0o600
