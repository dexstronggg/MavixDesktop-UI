from __future__ import annotations

import aiohttp

from mavixdesktop.core.config import settings
from mavixdesktop.core.logger import logger


class ApiError(Exception):
    pass


#### HTTP-клиент REST API ##############################################################
class ApiSession:
    """HTTP-клиент REST API MavixServer: login, refresh, ice-servers, list-drones."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    @classmethod
    async def create(cls) -> ApiSession:
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
            logger.debug('[api] ошибка проверки health: %s', exc)
            return False

#### Аутентификация ####################################################################
    async def login(self, email: str, password: str) -> dict:
        async with self._session.post(
            f'{settings.http_url}/api/v1/auth/login',
            json={'email': email, 'password': password},
        ) as r:
            data = await r.json()
            if r.status != 200:
                raise ApiError(data.get('detail', 'вход не удался'))
            return data

    async def operator_login(self, username: str, password: str) -> dict:
        """Вход оператора в desktop по username/password (выдаёт админ).

        Возвращает пару токенов с ролью operator (sub=operator_id).
        """
        async with self._session.post(
            f'{settings.http_url}/api/v1/auth/operator/login',
            json={'username': username, 'password': password},
        ) as r:
            data = await r.json()
            if r.status != 200:
                raise ApiError(data.get('detail', 'вход не удался'))
            return data

    async def refresh(self, refresh_token: str) -> dict:
        async with self._session.post(
            f'{settings.http_url}/api/v1/auth/operator/refresh',
            json={'refresh_token': refresh_token},
        ) as r:
            data = await r.json()
            if r.status != 200:
                raise ApiError(data.get('detail', 'обновление токена не удалось'))
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
                raise ApiError(data.get('detail', 'запрос восстановления пароля не удался'))
            return data

#### ICE-серверы и дроны ###############################################################
    async def ice_servers(self) -> list[dict]:
        try:
            async with self._session.get(f'{settings.http_url}/api/v1/ice-servers') as r:
                if r.status != 200:
                    return []
                data = await r.json()
                servers = data.get('ice_servers', [])
                return servers if isinstance(servers, list) else []
        except aiohttp.ClientError as exc:
            logger.warning('[api] ошибка получения ice-servers: %s', exc)
            return []

    async def delete_drone(self, drone_id: str, access_token: str) -> None:
        """Удаляет дрон по REST API. Кидает ApiError на любую ошибку
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

#### Доставки (оператор) ###############################################################
    async def _delivery_post(self, path: str, access_token: str) -> dict:
        url = f'{settings.http_url}/api/v1/deliveries/{path}'
        headers = {'Authorization': f'Bearer {access_token}'}
        async with self._session.post(url, headers=headers) as r:
            data = await r.json()
            if r.status != 200:
                raise ApiError(data.get('detail', f'операция не удалась (HTTP {r.status})'))
            return data

    async def get_my_delivery(self, access_token: str) -> dict | None:
        """Активная заявка оператора (accepted / in_flight). None если нет."""
        headers = {'Authorization': f'Bearer {access_token}'}
        try:
            async with self._session.get(
                f'{settings.http_url}/api/v1/deliveries/my', headers=headers,
            ) as r:
                if r.status == 404:
                    return None
                if r.status != 200:
                    return None
                return await r.json()
        except aiohttp.ClientError as exc:
            logger.debug('[api] ошибка получения активной заявки: %s', exc)
            return None

    async def list_offered_deliveries(self, access_token: str) -> list[dict]:
        """Заявки со статусом offered для админа этого оператора."""
        url = f'{settings.http_url}/api/v1/deliveries/offered'
        headers = {'Authorization': f'Bearer {access_token}'}
        async with self._session.get(url, headers=headers) as r:
            if r.status != 200:
                return []
            data = await r.json()
            return data if isinstance(data, list) else []

    async def accept_delivery(self, delivery_id: str, access_token: str) -> dict:
        """Принять заявку (гонка «такси»). 409 → уже принята другим."""
        return await self._delivery_post(f'{delivery_id}/accept', access_token)

    async def set_delivery_in_flight(self, delivery_id: str, access_token: str) -> dict:
        return await self._delivery_post(f'{delivery_id}/in-flight', access_token)

    async def mark_delivery_delivered(self, delivery_id: str, access_token: str) -> dict:
        """Отметить груз доставленным (после сброса) — сервер уведомит админа."""
        return await self._delivery_post(f'{delivery_id}/delivered', access_token)
