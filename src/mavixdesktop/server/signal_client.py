from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import websockets
from websockets.asyncio.client import connect as ws_connect

from mavixdesktop.core.logger import logger

if TYPE_CHECKING:
    from websockets.asyncio.client import ClientConnection


#### Сигнальный WebSocket-клиент #######################################################
class SignalClient:
    """Тонкий WebSocket-клиент для /ws/gcs.

    Авторизация идёт через первое сообщение {type:auth, token:<access_jwt>}
    после accept (паттерн сервера, а не кастомный заголовок).
    """

    def __init__(self, url: str, access_token: str) -> None:
        self._url = url
        self._access_token = access_token
        self._conn: ClientConnection | None = None

    @property
    def is_connected(self) -> bool:
        return self._conn is not None

    def update_access_token(self, new_token: str) -> None:
        """Используется координатором после round-trip refresh_auth."""
        self._access_token = new_token

    async def connect(self) -> bool:
        try:
            self._conn = await ws_connect(self._url)
        except (OSError, websockets.exceptions.InvalidURI, websockets.exceptions.InvalidHandshake) as exc:
            logger.info('[signal] ошибка подключения: %s', exc)
            self._conn = None
            return False
        try:
            await self._conn.send(json.dumps({'type': 'auth', 'token': self._access_token}))
        except (websockets.exceptions.ConnectionClosed, OSError) as exc:
            logger.info('[signal] ошибка отправки auth: %s', exc)
            await self.disconnect()
            return False
        return True

    async def disconnect(self) -> None:
        if self._conn is None:
            return
        try:
            await self._conn.close()
        except (websockets.exceptions.ConnectionClosed, OSError) as exc:
            logger.debug('[signal] ошибка отключения: %s', exc)
        finally:
            self._conn = None

#### Обмен сообщениями #################################################################
    async def send(self, payload: dict) -> None:
        if self._conn is None:
            raise RuntimeError('signal-клиент не подключён')
        await self._conn.send(json.dumps(payload))

    async def listen(self, on_message: Callable[[dict], Awaitable[None]]) -> None:
        if self._conn is None:
            raise RuntimeError('signal-клиент не подключён')
        async for raw in self._conn:
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning('[signal] некорректный json: %s', exc)
                continue
            await on_message(msg)
