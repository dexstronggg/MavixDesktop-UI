"""Заставляет H.264-декодер отдавать кадры без чистой точки восстановления.

По умолчанию ffmpeg молчит, пока не получит IDR или recovery point SEI. Если
борт кодирует с `intra-refresh`, IDR не появляется никогда, и после любой
рассинхронизации картинка не возвращается до пересоздания сессии: пакеты идут,
потерь нет, а `track.recv()` не отдаёт ни кадра (наблюдалось 30+ секунд подряд
при входящем потоке ~1.2 Мбит/с и `loss=0`). Флаг `show_all` снимает это
условие — декодер показывает и «грязный» кадр, который дочищается по мере
прохода волны intra-refresh.
"""

from __future__ import annotations

from typing import Any

from mavixdesktop.core.logger import logger

_applied = False


def _enable_show_all(codec_context: Any) -> bool:
    from av.codec.context import Flags2

    codec_context.flags2 |= Flags2.show_all
    return True


def install_decoder_patch() -> None:
    """Оборачивает создание H264Decoder в aiortc, включая show_all."""
    global _applied
    if _applied:
        return
    try:
        from aiortc.codecs import h264

        original_init = h264.H264Decoder.__init__

        def patched_init(self: Any, *args: Any, **kwargs: Any) -> None:
            original_init(self, *args, **kwargs)
            try:
                _enable_show_all(self.codec)
            except Exception as exc:
                logger.warning('[webrtc] show_all не включился: %s', exc)

        h264.H264Decoder.__init__ = patched_init  # type: ignore[method-assign]
        _applied = True
        logger.info('[webrtc] декодер-патч установлен: show_all — картинка не ждёт IDR')
    except Exception as exc:
        logger.error('[webrtc] декодер-патч не применился: %s', exc)
