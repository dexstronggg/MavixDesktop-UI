"""App-wide settings.

Precedence (highest wins):
  1. OS env vars
  2. ~/.config/mavixdesktop/config.json (Settings UI writes here)
  3. .env at the project root (only meaningful when running from sources)
  4. defaults below

The JSON path is the one the user actually edits via the in-app
Settings page. The .env at the project root is a dev convenience and
does not exist inside the installed PyInstaller bundle.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from mavixdesktop.core import user_config

_PROJECT_ROOT = Path(__file__).parents[3]

# Project-root .env is for development only; in an installed bundle
# this path resolves into _MEIPASS and finds nothing - harmless.
load_dotenv(_PROJECT_ROOT / '.env', override=False)

# User config JSON overrides .env / defaults but loses to OS env vars.
user_config.apply_to_env()

_USER_BASE = Path.home() / '.config' / 'mavixdesktop'


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / '.env'),
        env_file_encoding='utf-8',
        populate_by_name=True,
        extra='ignore',
    )

    # --- Server ---
    signal_url: str = Field(default='https://drone-mavix.ru', alias='SIGNAL_URL')

    # --- WebRTC ICE overrides ---
    # If left empty, the desktop uses whatever the server returns from
    # /api/v1/ice-servers. Defaults below mirror the production STUN/TURN
    # so a fresh install reaches the right relay even before logging in.
    stun_server: str = Field(default='stun:85.198.102.188:3478', alias='STUN_SERVER')
    turn_server: str = Field(default='turn:85.198.102.188:3478', alias='TURN_SERVER')
    turn_username: str = Field(default='myuser', alias='TURN_USERNAME')
    turn_password: str = Field(default='BxBF+DZ0JZU6lK1MiSyj8oG/+gwKJeIF', alias='TURN_PASSWORD')

    # --- QGC / MAVLink relay ---
    qgc_host: str = Field(default='127.0.0.1', alias='QGC_HOST')
    qgc_port: int = Field(default=14550, alias='QGC_PORT')
    qgc_bind_port: int = Field(default=0, alias='QGC_BIND_PORT')

    # --- Paths ---
    data_path: Path = _USER_BASE / 'data'
    log_path: Path = Field(default_factory=lambda: _USER_BASE / 'logs' / f'mavixdesktop_{date.today()}.log')
    config_dir: Path = _USER_BASE

    # --- Auth ---
    keyring_service: str = Field(default='mavixdesktop', alias='KEYRING_SERVICE')

    @property
    def ws_url(self) -> str:
        base = self.signal_url
        if base.startswith('https://'):
            return 'wss://' + base[len('https://'):].rstrip('/') + '/ws/gcs'
        if base.startswith('http://'):
            return 'ws://' + base[len('http://'):].rstrip('/') + '/ws/gcs'
        return base.rstrip('/') + '/ws/gcs'

    @property
    def http_url(self) -> str:
        return self.signal_url.rstrip('/')


settings = Settings()


def reload_from_user_config() -> None:
    """Re-read the JSON config and update the global `settings` object
    in place. Called by the Settings UI after a save so the rest of the
    app sees the new values without a restart."""
    user_config.apply_to_env()
    fresh = Settings()
    for field_name in fresh.model_fields:
        setattr(settings, field_name, getattr(fresh, field_name))
