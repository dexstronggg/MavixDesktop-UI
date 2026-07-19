"""Global application settings."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from mavixdesktop.core import user_config

_PROJECT_ROOT = Path(__file__).parents[3]

load_dotenv(_PROJECT_ROOT / '.env', override=False)

user_config.apply_to_env()

_USER_BASE = Path.home() / '.config' / 'mavixdesktop'


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / '.env'),
        env_file_encoding='utf-8',
        populate_by_name=True,
        extra='ignore',
    )

    signal_url: str = Field(default='https://drone-mavix.ru', alias='SIGNAL_URL')
    signal_ws_url: str = Field(default='', alias='SIGNAL_WS_URL')

    stun_server: str = Field(default='', alias='STUN_SERVER')
    turn_server: str = Field(default='', alias='TURN_SERVER')
    turn_username: str = Field(default='', alias='TURN_USERNAME')
    turn_password: str = Field(default='', alias='TURN_PASSWORD')

    qgc_host: str = Field(default='127.0.0.1', alias='QGC_HOST')
    qgc_port: int = Field(default=14550, alias='QGC_PORT')
    qgc_bind_port: int = Field(default=0, alias='QGC_BIND_PORT')

    force_relay: bool = Field(default=False, alias='FORCE_RELAY')

    debug: bool = Field(default=False, alias='DEBUG')

    data_path: Path = _USER_BASE / 'data'
    log_path: Path = Field(default_factory=lambda: _USER_BASE / 'logs' / f'mavixdesktop_{date.today()}.log')
    config_dir: Path = _USER_BASE

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


def reload_from_user_config() -> None:
    user_config.apply_to_env()
    fresh = Settings()
    for field_name in fresh.model_fields:
        setattr(settings, field_name, getattr(fresh, field_name))
