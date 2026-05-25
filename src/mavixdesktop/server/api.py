from __future__ import annotations

import aiohttp

from mavixdesktop.core.config import settings
from mavixdesktop.core.logger import logger


class ApiError(Exception):
    pass


class ApiSession:
    """HTTP client for MavixServer REST API: login, refresh, ice-servers, list-drones."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    @classmethod
    async def create(cls) -> 'ApiSession':
        return cls(aiohttp.ClientSession())

    async def close(self) -> None:
        await self._session.close()

    async def health(self) -> bool:
        try:
            async with self._session.get(f'{settings.http_url}/api/v1/health') as r:
                if r.status != 200:
                    return False
                data = await r.json()
                return data.get('status') == 'ok'
        except aiohttp.ClientError as exc:
            logger.debug('health check error: %s', exc)
            return False

    async def login(self, email: str, password: str) -> dict:
        async with self._session.post(
            f'{settings.http_url}/api/v1/auth/login',
            json={'email': email, 'password': password},
        ) as r:
            data = await r.json()
            if r.status != 200:
                raise ApiError(data.get('detail', 'login failed'))
            return data

    async def refresh(self, refresh_token: str) -> dict:
        async with self._session.post(
            f'{settings.http_url}/api/v1/auth/refresh',
            json={'refresh_token': refresh_token},
        ) as r:
            data = await r.json()
            if r.status != 200:
                raise ApiError(data.get('detail', 'refresh failed'))
            return data

    async def password_reset_request(self, email: str) -> dict:
        """Запрос восстановления пароля. Сервер всегда возвращает 200
        (anti-enumeration: не раскрывает, существует ли email в БД) —
        UI показывает одинаковое сообщение независимо от ответа.
        """
        async with self._session.post(
            f'{settings.http_url}/api/v1/auth/password-reset/request',
            json={'email': email},
        ) as r:
            try:
                data = await r.json()
            except Exception:
                data = {}
            if r.status != 200:
                raise ApiError(data.get('detail', 'password reset request failed'))
            return data

    async def ice_servers(self) -> list[dict]:
        try:
            async with self._session.get(f'{settings.http_url}/api/v1/ice-servers') as r:
                if r.status != 200:
                    return []
                data = await r.json()
                servers = data.get('ice_servers', [])
                return servers if isinstance(servers, list) else []
        except aiohttp.ClientError as exc:
            logger.warning('ice-servers fetch error: %s', exc)
            return []

    async def delete_drone(self, drone_id: str, access_token: str) -> None:
        """Удалить дрон по REST API. Кидает ApiError на любую ошибку
        кроме 204."""
        url = f'{settings.http_url}/api/v1/drones/{drone_id}'
        headers = {'Authorization': f'Bearer {access_token}'}
        async with self._session.delete(url, headers=headers) as r:
            if r.status == 204:
                return
            detail = ''
            try:
                data = await r.json()
                detail = data.get('detail', '')
            except (aiohttp.ContentTypeError, ValueError):
                pass
            if r.status == 401:
                raise ApiError('Сессия истекла, войдите снова')
            if r.status == 403:
                raise ApiError('Дрон вам не принадлежит')
            if r.status == 404:
                raise ApiError('Дрон уже удалён или не найден')
            raise ApiError(detail or f'Не удалось удалить дрон (HTTP {r.status})')
