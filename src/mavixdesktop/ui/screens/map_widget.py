"""Виджет карты для полётного экрана.

Загружает локальный Leaflet-ассет (HTML + leaflet-rotate через CDN unpkg) в
QWebEngineView и обновляет позицию дрона/поворот карты по телеметрии:
карта вращается так, чтобы курс дрона смотрел ВВЕРХ (bearing = -heading).
Маркер назначения берётся из принятой заявки.

QtWebEngine импортируется лениво — окружения без libGL не могут его
загрузить; карта в таком случае просто не создаётся, а полётный экран
остаётся рабочим (видео/джойстик/MAVLink не зависят от карты).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from mavixdesktop.core.logger import logger
from mavixdesktop.ui.style import theme

_MAP_HTML = Path(__file__).resolve().parents[1] / 'assets' / 'map' / 'map.html'


class MapWidget(QFrame):
    """Карта в углу полётного экрана.

    Если QtWebEngine недоступен (например, нет libGL), виджет деградирует до
    статичной плашки-заглушки — без падения остального UI.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName('mapWidget')
        self.setStyleSheet(f"""
            QFrame#mapWidget {{
                background: {theme.BG};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS_MD}px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._view = None
        self._ready = False
        self._pending_destination: tuple[float, float] | None = None

        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtWebEngineCore import QWebEngineSettings
            self._view = QWebEngineView(self)
            # Разрешаем file://-странице грузить тайлы с внешних https-адресов
            # (OSM tile server). Без этого Chromium блокирует cross-origin запросы.
            settings = self._view.settings()
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
            self._view.loadFinished.connect(self._on_load_finished)
            if _MAP_HTML.exists():
                self._view.load(QUrl.fromLocalFile(str(_MAP_HTML)))
            else:
                logger.warning('[map] ассет карты не найден: %s', _MAP_HTML)
            layout.addWidget(self._view)
        except Exception as exc:
            logger.warning('[map] QtWebEngine недоступен, карта отключена: %s', exc)
            placeholder = QLabel('Карта недоступна', self)
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet(
                f'color: {theme.TEXT_MUTED}; background: transparent;'
                f'font-size: {theme.FONT_SIZE_SM}px;'
            )
            layout.addWidget(placeholder)

    #### Публичный API #####################################################################
    def update_telemetry(self, lat: float, lon: float, heading: float) -> None:
        """Обновляет маркер дрона и поворот карты (курс → вверх)."""
        self._run_js(f'updateDrone({lat}, {lon}, {heading});')

    def set_destination(self, lat: float, lon: float) -> None:
        """Ставит маркер точки назначения (из принятой заявки)."""
        if not self._ready:
            self._pending_destination = (lat, lon)
            return
        self._run_js(f'setDestination({lat}, {lon});')

    #### Внутреннее ########################################################################
    def _on_load_finished(self, ok: bool) -> None:
        self._ready = bool(ok)
        if not ok:
            logger.warning('[map] не удалось загрузить HTML карты')
            return
        if self._pending_destination is not None:
            lat, lon = self._pending_destination
            self._pending_destination = None
            self._run_js(f'setDestination({lat}, {lon});')

    def _run_js(self, script: str) -> None:
        if self._view is None or not self._ready:
            return
        try:
            self._view.page().runJavaScript(script)
        except Exception as exc:
            logger.debug('[map] ошибка runJavaScript: %s', exc)


def telemetry_to_args(payload: dict) -> tuple[float, float, float] | None:
    """Извлекает (lat, lon, heading) из telemetry-payload дрона.

    Возвращает None, если нет валидных координат (lat/lon обязательны;
    heading по умолчанию 0). JSON-числа приводятся к float безопасно.
    """
    try:
        lat = float(payload['lat'])
        lon = float(payload['lon'])
    except (KeyError, TypeError, ValueError):
        return None
    try:
        heading = float(payload.get('heading', 0.0))
    except (TypeError, ValueError):
        heading = 0.0
    return lat, lon, heading
