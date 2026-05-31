"""WebRTC peer-сессия на стороне GCS.

Desktop — отвечающая сторона в этом обмене сигналингом: дрон шлёт SDP-offer
(с media-треками и заранее согласованными дескрипторами data-каналов), мы
ставим его как remote, создаём answer, ставим его как local и отправляем
answer обратно на сигнальный сервер.

Data-каналы (packet / ping / config) *создаёт* дрон; мы получаем их через
событие pc.on('datachannel'), поэтому, в отличие от peer'а MavixBoard, сами
ничего не эмитим.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING

from aiortc import (
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
)

from mavixdesktop.core.config import settings
from mavixdesktop.core.logger import logger

if TYPE_CHECKING:
    from aiortc import MediaStreamTrack, RTCDataChannel

TrackHandler = Callable[['MediaStreamTrack'], None]
DataChannelHandler = Callable[['RTCDataChannel'], None]


def _patch_dtls_setup_passive(sdp: str) -> str:
    """Переписывает каждую строку `a=setup:active` в SDP на `a=setup:passive`.

    Нужно для совместимости со стороной дрона на GStreamer `webrtcbin`
    (полное обоснование — в PeerSession.apply_offer).
    """
    out_lines: list[str] = []
    for line in sdp.splitlines(keepends=True):
        stripped = line.rstrip('\r\n')
        if stripped == 'a=setup:active':
            ending = line[len(stripped):]
            out_lines.append('a=setup:passive' + ending)
        else:
            out_lines.append(line)
    return ''.join(out_lines)


_CAND_RE = re.compile(r'^a=candidate:.* typ (\w+) ', re.MULTILINE)


def _log_candidates(label: str, sdp: str) -> None:
    """Логирует каждую ICE-candidate строку по типу. Используется, чтобы видеть,
    что aiortc реально собрал / что предложил дрон."""
    by_type: dict[str, list[str]] = {}
    for line in sdp.splitlines():
        if not line.startswith('a=candidate:'):
            continue
        m = _CAND_RE.match(line)
        if not m:
            continue
        by_type.setdefault(m.group(1), []).append(line)
    if not by_type:
        logger.info('[ice/%s] нет кандидатов в SDP', label)
        return
    for typ, lines in by_type.items():
        logger.info('[ice/%s] %s x%d', label, typ, len(lines))
        for cand in lines:
            logger.info('[ice/%s]   %s', label, cand.strip())


def _filter_to_relay_only(sdp: str, label: str) -> str:
    """Выбрасывает из SDP все non-relay кандидаты. Используется при
    settings.force_relay=True, чтобы имитировать сеть, где host/srflx пути
    заблокированы (например, корпоративный/университетский firewall). Удобно
    для воспроизведения упавших соединений локально, не выезжая в ту сеть.

    `a=end-of-candidates` и всё остальное сохраняется как есть."""
    kept = 0
    dropped = 0
    out_lines: list[str] = []
    for line in sdp.splitlines(keepends=True):
        if line.startswith('a=candidate:'):
            m = _CAND_RE.match(line)
            if m and m.group(1) != 'relay':
                dropped += 1
                continue
            kept += 1
        out_lines.append(line)
    if kept or dropped:
        logger.info('[ice/%s] force_relay фильтр: оставлено %d relay, отброшено %d non-relay',
                    label, kept, dropped)
    return ''.join(out_lines)


def _entry_scheme(entry: dict) -> str:
    """Возвращает scheme первого URL в записи RTCIceServer (stun/stuns/turn/turns/'')."""
    urls = entry.get('urls') if isinstance(entry, dict) else None
    if not urls:
        return ''
    url = urls if isinstance(urls, str) else (urls[0] if urls else '')
    if not isinstance(url, str) or ':' not in url:
        return ''
    return url.split(':', 1)[0].strip().lower()


def _build_configuration(ice_servers: list[dict]) -> RTCConfiguration:
    """Фильтрует ICE-серверы под текущий режим force_relay и собирает RTCConfiguration.

    Почему фильтр в принципе нужен: aiortc держит ровно один STUN и ровно
    один TURN сервер (rtcicetransport.py: второй URL c тем же scheme молча
    отбрасывается). При force_relay нам нужен ТОЛЬКО TURN — STUN-запись
    может «занять слот» и заодно сбивает iceTransportPolicy='relay',
    добавляя на сторону переговоров лишние srflx-кандидаты. При выключенном
    force_relay, наоборот, TURN-запись не нужна: всё равно политика 'all'
    предпочтёт прямую пару, а лишний TURN-сервер только удлиняет gathering."""
    use_relay = bool(getattr(settings, 'force_relay', False))
    mode = 'RELAY (только TURN)' if use_relay else 'DIRECT (только STUN)'
    logger.info('[ice/config] режим=%s, force_relay=%s, получено %d ICE-сервер(ов)',
                mode, use_relay, len(ice_servers))
    servers: list[RTCIceServer] = []
    for entry in ice_servers:
        urls = entry.get('urls') if isinstance(entry, dict) else None
        if not urls:
            continue
        scheme = _entry_scheme(entry)
        is_turn = scheme in ('turn', 'turns')
        is_stun = scheme in ('stun', 'stuns')
        if use_relay and not is_turn:
            logger.info('[ice/config] пропускаем non-TURN (%s) — force_relay включён', urls)
            continue
        if not use_relay and not is_stun:
            logger.info('[ice/config] пропускаем non-STUN (%s) — force_relay выключен', urls)
            continue
        username = entry.get('username')
        credential = entry.get('credential')
        kwargs: dict = {'urls': urls}
        if username:
            kwargs['username'] = username
        if credential:
            kwargs['credential'] = credential
        servers.append(RTCIceServer(**kwargs))
        logger.info('[ice/config] ИСПОЛЬЗУЕМ %s: urls=%s username=%s',
                    scheme.upper(), urls, bool(username))
    if not servers:
        logger.warning('[ice/config] после фильтрации не осталось ICE-серверов — '
                       'соединение, скорее всего, упадёт. Проверьте локальный STUN/TURN-конфиг '
                       '(или /api/v1/ice-servers) и настройку force_relay (текущая: %s).', use_relay)
    # У aiortc нет iceTransportPolicy на RTCConfiguration, поэтому форсируем
    # relay нативно на уровне aioice (см. relay_patch). Хук сам гейтится по
    # settings.force_relay + наличию TURN per-connection; установка дёшева и
    # идемпотентна.
    from mavixdesktop.webrtc.relay_patch import enable_relay_only
    enable_relay_only()
    if use_relay and not servers:
        logger.warning('[ice/config] force_relay запрошен, но TURN-сервера нет — '
                       'relay-путь использовать нельзя')
    logger.info('[ice/config] transport policy=%s (нативно через aioice)',
                'relay' if (use_relay and servers) else 'all')
    return RTCConfiguration(iceServers=servers)


class PeerSession:
    """Одна активная WebRTC-сессия с одним дроном. Создаётся при возврате
    'connect' от сервера, уничтожается, когда GCS или дрон разрывают пару."""

    def __init__(
        self,
        drone_id: str,
        ice_servers: list[dict] | None = None,
        pc: RTCPeerConnection | None = None,
    ) -> None:
        self.drone_id = drone_id
        self._pc = pc if pc is not None else RTCPeerConnection(
            _build_configuration(ice_servers or [])
        )
        self.on_track: TrackHandler | None = None
        self.on_datachannel: DataChannelHandler | None = None

        self._pc.add_listener('track', self._handle_track)
        self._pc.add_listener('datachannel', self._handle_datachannel)
        self._pc.add_listener('iceconnectionstatechange', self._handle_ice_state)
        self._pc.add_listener('icegatheringstatechange', self._handle_gather_state)
        self._pc.add_listener('connectionstatechange', self._handle_conn_state)

    @property
    def pc(self) -> RTCPeerConnection:
        return self._pc

    @property
    def connection_state(self) -> str:
        return self._pc.connectionState

    async def apply_offer(self, sdp_text: str) -> str:
        """Ставит offer дрона как remote, строит answer, возвращает его sdp.

        ВАЖНО: в возвращаемом SDP каждый `a=setup:active` переписан на
        `a=setup:passive`. Это критично: дрон использует GStreamer
        `webrtcbin`, который всегда хочет быть DTLS-клиентом
        (`a=setup:active`). aiortc по умолчанию здесь тоже возвращает
        `a=setup:active`. Когда обе стороны заявляют active, DTLS-handshake
        никогда не завершается — симптом на стороне дрона «Fatal SSL error» /
        зависший DTLS. Принудительный passive в answer GCS делает aiortc
        DTLS-сервером и разблокирует переговоры. Удаление этой правки ломает
        каждую сессию.
        """
        logger.info('[peer] m-линии offer: %s',
                    [line for line in sdp_text.splitlines() if line.startswith('m=')])

        # 1. Логируем входящие кандидаты от дрона.
        _log_candidates('offer/drone', sdp_text)

        # 2. Опционально: имитируем корпоративный NAT — отбрасываем host/srflx
        # из offer дрона, чтобы остались только его relay-кандидаты.
        # Фактически форсирует relay-relay путь.
        if getattr(settings, 'force_relay', False):
            sdp_text = _filter_to_relay_only(sdp_text, 'offer/drone')

        await self._pc.setRemoteDescription(
            RTCSessionDescription(sdp=sdp_text, type='offer')
        )
        answer = await self._pc.createAnswer()
        patched_answer = RTCSessionDescription(
            sdp=_patch_dtls_setup_passive(answer.sdp),
            type=answer.type,
        )
        await self._pc.setLocalDescription(patched_answer)
        assert self._pc.localDescription is not None
        final_sdp = _patch_dtls_setup_passive(self._pc.localDescription.sdp)

        # 3. Логируем собственные собранные кандидаты.
        _log_candidates('answer/gcs', final_sdp)

        # 4. Тот же фильтр на нашей стороне, если включён force_relay.
        if getattr(settings, 'force_relay', False):
            final_sdp = _filter_to_relay_only(final_sdp, 'answer/gcs')

        logger.info('[peer] m-линии answer: %s',
                    [line for line in final_sdp.splitlines() if line.startswith('m=')])
        return final_sdp

    async def add_remote_ice(self, candidate: dict) -> bool:
        """Применяет один ICE-кандидат, полученный с сигнального сервера.

        Дрон (GStreamer/libnice) trickle-ит свои кандидаты, поэтому надо
        парсить всю candidate-строку. aiortc строит нижележащий aioice-
        кандидат из РАЗОБРАННЫХ полей (ip/port/foundation/priority/type), а
        НЕ из сырой строки `.candidate` — поэтому парсим через
        candidate_from_sdp. (Старый код заполнял только .candidate и оставлял
        ip/port пустыми, поэтому aioice отвергал каждый trickled-кандидат как
        «not a valid IPv4/IPv6 address», и relay-кандидат дрона молча
        отбрасывался — нет remote-кандидата, нет ICE.)
        """
        try:
            from aiortc.sdp import candidate_from_sdp
            cand_str = candidate.get('candidate')
            sdp_mid = candidate.get('sdpMid')
            sdp_mline_index = candidate.get('sdpMLineIndex')
            if not isinstance(cand_str, str) or not cand_str.strip():
                # пустой candidate = маркер end-of-candidates, добавлять нечего
                return False
            # candidate_from_sdp хочет значение без префикса "candidate:"
            sdp_str = cand_str[len('candidate:'):] if cand_str.startswith('candidate:') else cand_str
            # force_relay: отбрасываем non-relay trickle-кандидаты. На всякий
            # случай — aioice уже relay-only через relay_patch; это лишь убирает шум.
            if getattr(settings, 'force_relay', False) and ' typ ' in sdp_str:
                typ = sdp_str.split(' typ ', 1)[1].split(' ', 1)[0]
                if typ != 'relay':
                    logger.info('[ice/trickle] отброшен non-relay кандидат: %s', cand_str)
                    return False
            try:
                ice = candidate_from_sdp(sdp_str)
            except (AssertionError, ValueError, IndexError):
                logger.info('[ice/trickle] пропускаем неразбираемый кандидат: %r', cand_str)
                return False
            ice.sdpMid = sdp_mid
            ice.sdpMLineIndex = sdp_mline_index
            logger.info('[ice/trickle] добавляем кандидат type=%s %s:%s', ice.type, ice.ip, ice.port)
            await self._pc.addIceCandidate(ice)
            return True
        except Exception as exc:
            logger.warning('[peer] ошибка add_remote_ice: %s', exc)
            return False

    async def close(self) -> None:
        try:
            await self._pc.close()
        except Exception as exc:
            logger.debug('[peer] ошибка close: %s', exc)

    def _handle_track(self, track: MediaStreamTrack) -> None:
        logger.info('[peer] событие track: kind=%s id=%s', track.kind, track.id)
        if self.on_track is None:
            logger.warning('[peer] обработчик on_track is None, отбрасываем track')
            return
        try:
            self.on_track(track)
        except Exception as exc:
            logger.warning('[peer] ошибка обработчика on_track: %s', exc)

    def _handle_datachannel(self, channel: RTCDataChannel) -> None:
        if self.on_datachannel is None:
            return
        try:
            self.on_datachannel(channel)
        except Exception as exc:
            logger.warning('[peer] ошибка обработчика on_datachannel: %s', exc)

    def _handle_ice_state(self) -> None:
        state = self._pc.iceConnectionState
        logger.info('[ice/state] iceConnectionState=%s', state)
        if state == 'failed':
            logger.warning('[ice/state] ICE failed — нет работающей кандидат-пары. '
                           'Проверьте логи [ice/offer/drone] и [ice/answer/gcs] выше: '
                           'обе стороны должны иметь хотя бы по одному relay-кандидату.')

    def _handle_gather_state(self) -> None:
        logger.info('[ice/state] iceGatheringState=%s', self._pc.iceGatheringState)

    def _handle_conn_state(self) -> None:
        logger.info('[ice/state] connectionState=%s', self._pc.connectionState)
