"""Карта дрона на чистом QPainter (без QtWebEngine).

Рисует растровые тайлы (спутник Esri по умолчанию / OSM-улицы по тумблеру),
качает их асинхронно через QNetworkAccessManager и кэширует в памяти и на
диске. Карта вращается по курсу дрона (нос — всегда вверх), сверху рисуются
маркер дрона, маркер точки назначения и линия с дистанцией до неё.

Почему не QtWebEngine: Chromium-движок ронял всё приложение при открытии QGC
на машинах с капризной libGL. Тут только QtWidgets + QPainter (софт-растр) —
ни Chromium, ни GL-контекста, ни блокирующих вызовов на UI-потоке.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt, QUrl
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPixmap, QPolygonF
from PySide6.QtWidgets import QFrame, QPushButton, QWidget

from mavixdesktop.core.config import settings
from mavixdesktop.core.logger import logger
from mavixdesktop.ui.style import theme

#### Проекция тайлов (чистые функции, без Qt — покрыты юнит-тестами) ###################
TILE_SIZE = 256


def lonlat_to_world_px(lat: float, lon: float, z: int) -> tuple[float, float]:
    """Координаты точки в «мировых» пикселях Web Mercator на зуме z."""
    n = TILE_SIZE * (2 ** z)
    x = (lon + 180.0) / 360.0 * n
    lat = max(-85.05112878, min(85.05112878, lat))
    lat_rad = math.radians(lat)
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Дистанция между двумя точками по большому кругу, в метрах."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


#### Источники тайлов ##################################################################
_SOURCES = {
    'sat': {
        'label': 'Спутник',
        'next': 'osm',
        # Esri World Imagery — порядок {z}/{y}/{x}.
        'url': 'https://server.arcgisonline.com/ArcGIS/rest/services/'
               'World_Imagery/MapServer/tile/{z}/{y}/{x}',
    },
    'osm': {
        'label': 'Улицы',
        'next': 'sat',
        'url': 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    },
}
_USER_AGENT = b'MavixDesktop/1.0 (delivery GCS)'
_MEM_CACHE_MAX = 512


class MapWidget(QFrame):
    """Мини-карта дрона. Публичный API совместим с прежним виджетом:
    update_telemetry(lat, lon, heading) и set_destination(lat, lon)."""

    def __init__(self, parent: QWidget | None = None, zoom: int = 16) -> None:
        super().__init__(parent)
        self._zoom = zoom
        self._lat: float | None = None
        self._lon: float | None = None
        self._heading = 0.0
        self._dest: tuple[float, float] | None = None
        self._source = 'sat'
        self._rotate = True

        self._mem: dict[tuple, QPixmap] = {}
        self._pending: set[tuple] = set()
        self._nam = None  # QNetworkAccessManager создаём лениво (см. _ensure_nam)

        self.setStyleSheet(
            f'background: #0b0f14; border: 1px solid {theme.BORDER};'
            f'border-radius: {theme.RADIUS_MD}px;'
        )

        self._cache_dir = settings.data_path / 'tiles'

        # Тумблер слоя (спутник/улицы) — правый верхний угол карты.
        self._src_btn = QPushButton(_SOURCES[self._source]['label'], self)
        self._src_btn.setCursor(Qt.PointingHandCursor)
        self._src_btn.setFixedHeight(22)
        self._src_btn.setStyleSheet(
            'QPushButton { background: rgba(0,0,0,0.55); color: white;'
            ' border: 1px solid rgba(255,255,255,0.20); border-radius: 4px;'
            f' font-size: {theme.FONT_SIZE_SM - 3}px; padding: 0 8px; }}'
            ' QPushButton:hover { background: rgba(0,0,0,0.75); }'
        )
        self._src_btn.clicked.connect(self._toggle_source)

    #### Публичный API #####################################################################
    def update_telemetry(self, lat: float, lon: float, heading: float) -> None:
        self._lat, self._lon, self._heading = lat, lon, heading
        self.update()

    def set_destination(self, lat: float, lon: float) -> None:
        self._dest = (lat, lon)
        self.update()

    #### Сеть и кэш тайлов #################################################################
    def _ensure_nam(self):
        if self._nam is None:
            from PySide6.QtNetwork import QNetworkAccessManager
            self._nam = QNetworkAccessManager(self)
        return self._nam

    def _toggle_source(self) -> None:
        self._source = _SOURCES[self._source]['next']
        self._src_btn.setText(_SOURCES[self._source]['label'])
        self._src_btn.adjustSize()
        self.update()

    def _disk_path(self, z: int, x: int, y: int):
        return self._cache_dir / self._source / str(z) / f'{x}_{y}.png'

    def _tile(self, z: int, x: int, y: int) -> QPixmap | None:
        """Тайл из памяти/диска или None (тогда запускает асинхронную загрузку)."""
        key = (self._source, z, x, y)
        pm = self._mem.get(key)
        if pm is not None:
            return pm
        path = self._disk_path(z, x, y)
        if path.is_file():
            pm = QPixmap(str(path))
            if not pm.isNull():
                self._store_mem(key, pm)
                return pm
        if key not in self._pending:
            self._pending.add(key)
            self._request_tile(key, z, x, y)
        return None

    def _request_tile(self, key: tuple, z: int, x: int, y: int) -> None:
        from PySide6.QtNetwork import QNetworkRequest
        url = _SOURCES[self._source]['url'].format(z=z, x=x, y=y)
        req = QNetworkRequest(QUrl(url))
        req.setRawHeader(b'User-Agent', _USER_AGENT)
        reply = self._ensure_nam().get(req)
        reply.finished.connect(lambda r=reply, k=key: self._on_tile_loaded(r, k))

    def _on_tile_loaded(self, reply, key: tuple) -> None:
        from PySide6.QtNetwork import QNetworkReply
        self._pending.discard(key)
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                data = bytes(reply.readAll())
                pm = QPixmap()
                if pm.loadFromData(data) and not pm.isNull():
                    self._store_mem(key, pm)
                    self._save_disk(key, data)
                    self.update()
            else:
                logger.debug('[map] тайл не загружен: %s', reply.errorString())
        finally:
            reply.deleteLater()

    def _store_mem(self, key: tuple, pm: QPixmap) -> None:
        if len(self._mem) >= _MEM_CACHE_MAX:
            self._mem.pop(next(iter(self._mem)))
        self._mem[key] = pm

    def _save_disk(self, key: tuple, data: bytes) -> None:
        _, z, x, y = key
        path = self._disk_path(z, x, y)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        except OSError as exc:
            logger.debug('[map] не удалось сохранить тайл на диск: %s', exc)

    #### Отрисовка #########################################################################
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Тумблер — правый верхний угол с отступом.
        self._src_btn.adjustSize()
        self._src_btn.move(self.width() - self._src_btn.width() - 6, 6)
        self._src_btn.raise_()

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.fillRect(self.rect(), QColor('#0b0f14'))

        if self._lat is None or self._lon is None:
            p.setPen(QColor(theme.TEXT_MUTED))
            p.drawText(self.rect(), Qt.AlignCenter, 'Ожидание GPS…')
            p.end()
            return

        z = self._zoom
        w, h = self.width(), self.height()
        cx, cy = lonlat_to_world_px(self._lat, self._lon, z)
        max_tile = 2 ** z - 1

        p.save()
        p.translate(w / 2.0, h / 2.0)
        if self._rotate:
            p.rotate(-self._heading)

        # Радиус с запасом, чтобы углы не оголялись при повороте.
        radius = math.hypot(w, h) / 2.0 + TILE_SIZE
        min_tx = int((cx - radius) // TILE_SIZE)
        max_tx = int((cx + radius) // TILE_SIZE)
        min_ty = int((cy - radius) // TILE_SIZE)
        max_ty = int((cy + radius) // TILE_SIZE)
        for tx in range(min_tx, max_tx + 1):
            for ty in range(min_ty, max_ty + 1):
                if tx < 0 or ty < 0 or tx > max_tile or ty > max_tile:
                    continue
                pm = self._tile(z, tx, ty)
                if pm is not None:
                    p.drawPixmap(QPointF(tx * TILE_SIZE - cx, ty * TILE_SIZE - cy), pm)

        # Назначение и линия до него — вращаются вместе с картой.
        if self._dest is not None:
            dx, dy = lonlat_to_world_px(self._dest[0], self._dest[1], z)
            dpt = QPointF(dx - cx, dy - cy)
            p.setPen(QColor(0, 217, 255, 200))
            p.drawLine(QPointF(0, 0), dpt)
            p.setBrush(QColor(0, 217, 255))
            p.setPen(QColor('white'))
            p.drawEllipse(dpt, 5, 5)
        p.restore()

        # Маркер дрона — стрелка «носом вверх» в центре (карта повёрнута под него).
        p.translate(w / 2.0, h / 2.0)
        arrow = QPolygonF([QPointF(0, -9), QPointF(6, 7), QPointF(0, 3), QPointF(-6, 7)])
        p.setBrush(QColor(255, 80, 80))
        p.setPen(QColor('white'))
        p.drawPolygon(arrow)
        p.resetTransform()

        # Дистанция до точки назначения.
        if self._dest is not None:
            dist = haversine_m(self._lat, self._lon, self._dest[0], self._dest[1])
            txt = f'{dist:.0f} м' if dist < 1000 else f'{dist / 1000:.1f} км'
            p.setPen(QColor('white'))
            p.fillRect(6, h - 22, 86, 18, QColor(0, 0, 0, 140))
            p.drawText(8, h - 9, f'до точки: {txt}')
        p.end()


#### Парсинг телеметрии в аргументы карты ##############################################
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
