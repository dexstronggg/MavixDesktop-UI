"""Глобальные настройки приложения.

Приоритет (выше — главнее):
  1. переменные окружения ОС
  2. ~/.config/mavixdesktop/config.json (туда пишет Settings UI)
  3. .env в корне проекта (имеет смысл только при запуске из исходников)
  4. дефолты ниже

JSON-файл — это то, что пользователь реально правит через страницу
Settings внутри приложения. .env в корне проекта — удобство для
разработки и отсутствует внутри установленного PyInstaller-бандла.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from mavixdesktop.core import user_config

_PROJECT_ROOT = Path(__file__).parents[3]

# .env в корне проекта — только для разработки; в установленном бандле
# этот путь резолвится в _MEIPASS и ничего не находит — это безвредно.
load_dotenv(_PROJECT_ROOT / '.env', override=False)

# JSON пользователя перекрывает .env / дефолты, но уступает env-переменным ОС.
user_config.apply_to_env()

_USER_BASE = Path.home() / '.config' / 'mavixdesktop'


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / '.env'),
        env_file_encoding='utf-8',
        populate_by_name=True,
        extra='ignore',
    )

#### Сервер ############################################################################
    signal_url: str = Field(default='https://drone-mavix.ru', alias='SIGNAL_URL')

#### Переопределения WebRTC ICE ########################################################
    # Если оставить пустым, desktop использует то, что вернёт сервер из
    # /api/v1/ice-servers. Дефолты ниже повторяют production STUN/TURN,
    # чтобы свежая установка дотягивалась до нужного relay ещё до логина.
    stun_server: str = Field(default='stun:turn.drone-mavix.ru:3478', alias='STUN_SERVER')
    turn_server: str = Field(default='turns:turn.drone-mavix.ru:443', alias='TURN_SERVER')
    turn_username: str = Field(default='myuser', alias='TURN_USERNAME')
    turn_password: str = Field(default='BxBF+DZ0JZU6lK1MiSyj8oG/+gwKJeIF', alias='TURN_PASSWORD')

#### QGC / MAVLink relay ###############################################################
    qgc_host: str = Field(default='127.0.0.1', alias='QGC_HOST')
    qgc_port: int = Field(default=14550, alias='QGC_PORT')
    qgc_bind_port: int = Field(default=0, alias='QGC_BIND_PORT')

#### Отладка: force-relay ##############################################################
    # Если True, в SDP отбрасываются все candidate-строки кроме relay.
    # Имитирует корпоративный/университетский firewall, где host и srflx
    # пары не работают. Удобно для проверки, что TURN-only путь живой,
    # не выходя из домашней сети.
    force_relay: bool = Field(default=False, alias='FORCE_RELAY')

#### Отладка: debug-режим ##############################################################
    # Если True, приложение стартует на debug-странице (кнопки ручной проверки
    # функций без борта и сервера) и пишет лог на уровне DEBUG. Имеет смысл
    # только при запуске из исходников: .env в PyInstaller-бандле не читается.
    debug: bool = Field(default=False, alias='DEBUG')

#### Пути ##############################################################################
    data_path: Path = _USER_BASE / 'data'
    log_path: Path = Field(default_factory=lambda: _USER_BASE / 'logs' / f'mavixdesktop_{date.today()}.log')
    config_dir: Path = _USER_BASE

#### Аутентификация ####################################################################
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
    """Перечитывает JSON-конфиг и обновляет глобальный объект `settings`
    на месте. Вызывается из Settings UI после сохранения, чтобы остальное
    приложение увидело новые значения без перезапуска."""
    user_config.apply_to_env()
    fresh = Settings()
    for field_name in fresh.model_fields:
        setattr(settings, field_name, getattr(fresh, field_name))
