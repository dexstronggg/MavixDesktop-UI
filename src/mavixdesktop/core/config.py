from __future__ import annotations

from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).parents[3]

# When running as a PyInstaller single-file binary, _PROJECT_ROOT
# resolves into the temp extraction dir — useless for user config.
# Use the OS-standard user config path instead, with the project-root
# .env as a dev-time fallback.
_USER_CONFIG_ENV = Path.home() / '.config' / 'mavixdesktop' / '.env'
load_dotenv(_USER_CONFIG_ENV, override=False)
load_dotenv(_PROJECT_ROOT / '.env', override=True)

_USER_BASE = Path.home() / '.config' / 'mavixdesktop'


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / '.env'),
        env_file_encoding='utf-8',
        populate_by_name=True,
        extra='ignore',
    )

    # --- Server ---
    signal_url: str = Field(default='http://localhost:8000', alias='SIGNAL_URL')
    signal_ws_url: str = Field(default='', alias='SIGNAL_WS_URL')

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
        if self.signal_ws_url:
            return self.signal_ws_url
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
