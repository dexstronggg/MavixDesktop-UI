"""Пользовательский конфиг, сохраняемый в ~/.config/mavixdesktop/config.json.

Именно отсюда читает и сюда пишет Settings UI. Файл загружается при старте
(в core.config) и перекрывает дефолты, вшитые в бинарник. Переменные
окружения ОС всё равно главнее файла — так задумано, чтобы разработчик мог
переопределить что угодно из шелла.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mavixdesktop.core.logger import logger

USER_CONFIG_PATH = Path.home() / '.config' / 'mavixdesktop' / 'config.json'

# Какие ключи показывает Settings UI. Страница Settings рисует поля в этом
# порядке и сохраняет на диск только эти ключи — неизвестные ключи в файле
# сохраняются при записи, но игнорируются UI.
EDITABLE_KEYS = (
    'signal_url',
    'stun_server',
    'turn_server',
    'turn_username',
    'turn_password',
    'qgc_host',
    'qgc_port',
    'force_relay',
)


#### Чтение и запись JSON ##############################################################
def load() -> dict[str, Any]:
    """Читает JSON-конфиг. Возвращает пустой dict, если файла нет или он
    нечитаем — вызывающие откатываются на свои дефолты."""
    if not USER_CONFIG_PATH.is_file():
        return {}
    try:
        with USER_CONFIG_PATH.open('r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.warning('[user-config] %s не является JSON-объектом, игнорируем', USER_CONFIG_PATH)
            return {}
        return data
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning('[user-config] не удалось прочитать %s: %s', USER_CONFIG_PATH, exc)
        return {}


def save(values: dict[str, Any]) -> None:
    """Атомарно записывает JSON-конфиг. Создаёт каталог при необходимости."""
    USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = USER_CONFIG_PATH.with_suffix('.json.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(values, f, indent=2, ensure_ascii=False)
        f.write('\n')
    os.replace(tmp, USER_CONFIG_PATH)


#### Проекция в окружение ##############################################################
_MAPPING = {
    'signal_url':    'SIGNAL_URL',
    'stun_server':   'STUN_SERVER',
    'turn_server':   'TURN_SERVER',
    'turn_username': 'TURN_USERNAME',
    'turn_password': 'TURN_PASSWORD',
    'qgc_host':      'QGC_HOST',
    'qgc_port':      'QGC_PORT',
    'force_relay':   'FORCE_RELAY',
}

# Env-ключи, за которые сейчас отвечает JSON-слой, чтобы при reload их можно
# было безопасно очистить перед повторным применением свежего JSON. Ключ,
# пришедший из реальной env-переменной ОС (выставленной до первого импорта
# этого модуля), в это множество НЕ попадает и остаётся нетронутым.
_MANAGED_KEYS: set[str] = set()

# Ключи, существовавшие в ОС ДО загрузки .env через dotenv.
# Только они защищены от перезаписи через Settings UI.
# Инициализируется через init() из config.py до вызова load_dotenv.
_REAL_OS_KEYS: frozenset[str] = frozenset()


def init(real_os_keys: frozenset[str]) -> None:
    """Запоминает ключи настоящего окружения ОС (до dotenv).
    Вызывается один раз из config.py перед apply_to_env."""
    global _REAL_OS_KEYS
    _REAL_OS_KEYS = real_os_keys


def apply_to_env() -> None:
    """Проецирует JSON-конфиг в os.environ, чтобы pydantic-settings его
    подхватил. Только ключи из _REAL_OS_KEYS (настоящая env ОС, до dotenv)
    защищены от перезаписи. .env-значения и дефолты перекрываются.
    Последующие вызовы сбрасывают ранее управляемые ключи, чтобы очистка
    поля в Settings UI реально снимала значение."""
    # Удаляем всё, что выставили на прошлом проходе, чтобы пустое JSON-значение
    # реально опустошало env, а не оставляло устаревшее.
    for env_key in list(_MANAGED_KEYS):
        os.environ.pop(env_key, None)
    _MANAGED_KEYS.clear()

    data = load()
    if not data:
        return
    for json_key, env_key in _MAPPING.items():
        if env_key in _REAL_OS_KEYS:
            # Настоящая переменная ОС (выставлена до dotenv) — не трогаем.
            continue
        value = data.get(json_key)
        if value is None or value == '':
            continue
        os.environ[env_key] = str(value)
        _MANAGED_KEYS.add(env_key)
