from typing import Callable

from PySide6.QtCore import Qt, Signal, QTimer, QPointF
from PySide6.QtGui import QPixmap, QPainter, QIcon, QRadialGradient, QColor, QPainterPath
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame,
)

from mavixdesktop.ui.style import theme
from .utils import (
    svg_pixmap, mavix_logo_pixmap, AnimatedCard, CardGrid,
    accent_line, make_page_header, StatusPill,
)


def _brand_widget(parent: QWidget | None = None) -> QWidget:
    """Логотип-бренд: квадратик с M + надпись MAVIX + версия +
    online-индикатор, как в шапке сайта."""
    w = QWidget(parent)
    w.setStyleSheet('background: transparent;')
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(10)
    logo = QLabel()
    logo.setFixedSize(28, 28)
    logo.setPixmap(mavix_logo_pixmap(28))
    logo.setStyleSheet('background: transparent;')
    h.addWidget(logo)
    wordmark = QLabel('MAVIX')
    wordmark.setStyleSheet(
        f'background: transparent; color: {theme.TEXT_PRIMARY};'
        f'font-family: {theme.FONT_FAMILY_MONO}; font-weight: 600;'
        f'font-size: {theme.FONT_SIZE_BASE}px; letter-spacing: 2px;'
    )
    h.addWidget(wordmark)
    # Маленькая версия рядом с wordmark.
    version = QLabel('v0.1.0')
    version.setStyleSheet(
        f'background: transparent; color: {theme.TEXT_MUTED};'
        f'font-family: {theme.FONT_FAMILY_MONO}; font-weight: 500;'
        f'font-size: 10px; letter-spacing: 0.5px;'
    )
    h.addWidget(version)
    # Зелёная пульсирующая точка — индикатор «приложение живо».
    h.addSpacing(4)
    live = QLabel('●')
    live.setStyleSheet(
        f'background: transparent; color: {theme.STATUS_READY}; font-size: 8px;'
    )
    live.setToolTip('Приложение активно')
    h.addWidget(live)
    return w


def _icon_button(icon_name: str | None, text: str,
                 parent: QWidget | None = None) -> QPushButton:
    """Ghost-кнопка с опциональной SVG-иконкой + текстом.

    Если ``icon_name`` is None — кнопка только текстовая (используется
    для «Выйти», чтобы не делать акцент иконкой).
    """
    btn = QPushButton(text, parent)
    if icon_name is not None:
        btn.setIcon(QIcon(svg_pixmap(icon_name, 16, color=theme.TEXT_PRIMARY)))
    btn.setCursor(Qt.PointingHandCursor)
    btn.setStyleSheet(theme.QSS_BUTTON_SECONDARY)
    btn.setMinimumHeight(36)
    return btn

_CARD_W   = 180
_CARD_H   = 200
_ICON_SIZE = 88


def _dim_pixmap(src: QPixmap, opacity: float = 0.3) -> QPixmap:
    result = QPixmap(src.size())
    result.fill(Qt.transparent)
    p = QPainter(result)
    p.setOpacity(opacity)
    p.drawPixmap(0, 0, src)
    p.end()
    return result


class DroneCard(AnimatedCard):
    clicked = Signal(str)

    def __init__(self, session_id: str, status: str, index: int, icon_pixmap: QPixmap):
        super().__init__()
        self._session_id = session_id
        self._ready = (status == 'ready')

        self.setFixedSize(_CARD_W, _CARD_H)
        if self._ready:
            self.setCursor(Qt.PointingHandCursor)

        self._style_normal = f"""
            QWidget#droneCard {{
                background: {theme.BG_INPUT};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS_LG}px;
            }}
        """
        self._style_hover = f"""
            QWidget#droneCard {{
                background: {theme.BG_HOVER};
                border: 1px solid {theme.ACCENT};
                border-radius: {theme.RADIUS_LG}px;
            }}
        """
        self.setObjectName('droneCard')
        self.setStyleSheet(self._style_normal)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(6)
        layout.setContentsMargins(12, 18, 12, 14)

        icon_lbl = QLabel()
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setPixmap(icon_pixmap if self._ready else _dim_pixmap(icon_pixmap))
        icon_lbl.setStyleSheet('background: transparent; border: none;')

        name_lbl = QLabel(f'Дрон №{index + 1}')
        name_lbl.setAlignment(Qt.AlignCenter)
        name_lbl.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY if self._ready else theme.TEXT_DISABLED};'
            f'font-size: {theme.FONT_SIZE_SM}px; font-weight: 600;'
            'background: transparent; border: none;'
        )

        short_id = session_id[:6] if session_id else '??????'
        id_lbl = QLabel(short_id)
        id_lbl.setAlignment(Qt.AlignCenter)
        id_lbl.setStyleSheet(
            f'color: {theme.TEXT_MUTED if self._ready else theme.TEXT_DISABLED};'
            f'font-size: {theme.FONT_SIZE_SM - 3}px; font-family: monospace;'
            'background: transparent; border: none;'
        )

        # Status-pill вместо «● + текст».
        status_row = QWidget()
        status_row.setStyleSheet('background: transparent; border: none;')
        sr_layout = QHBoxLayout(status_row)
        sr_layout.setAlignment(Qt.AlignCenter)
        sr_layout.setSpacing(0)
        sr_layout.setContentsMargins(0, 0, 0, 0)
        pill_status = 'ready' if self._ready else (status or 'offline')
        sr_layout.addWidget(StatusPill(pill_status))

        layout.addWidget(icon_lbl)
        layout.addWidget(name_lbl)
        layout.addWidget(id_lbl)
        layout.addWidget(status_row)

    def _on_hover(self, hovered: bool):
        effective = hovered and self._ready
        self.setStyleSheet(self._style_hover if effective else self._style_normal)
        self._animate_bar(1000 if effective else 0)

    def mousePressEvent(self, event):
        if self._ready and event.button() == Qt.LeftButton:
            self.clicked.emit(self._session_id)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        # Лёгкий cyan-«отблеск» в правом верхнем углу — иллюзия
        # направленного света. Только для готовых карточек.
        if not self._ready:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # Обрезаем по форме карточки, чтобы не выходить за скругления.
        path = QPainterPath()
        path.addRoundedRect(
            0, 0, self.width(), self.height(),
            theme.RADIUS_LG, theme.RADIUS_LG,
        )
        p.setClipPath(path)
        grad = QRadialGradient(
            QPointF(self.width() - 10, 6), self.width() * 0.75
        )
        grad.setColorAt(0.0, QColor(34, 211, 238, 40))
        grad.setColorAt(0.6, QColor(34, 211, 238, 10))
        grad.setColorAt(1.0, QColor(34, 211, 238, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawRect(self.rect())
        p.end()


class _DroneGrid(CardGrid):
    CARD_W = _CARD_W
    CARD_H = _CARD_H
    GAP    = 20


class DroneListPage(QWidget):
    def __init__(self, on_select: Callable, on_refresh: Callable,
                 on_logout: Callable, on_joystick_cfg: Callable):
        super().__init__()
        self._on_select = on_select
        self._icon = svg_pixmap('drone_list.svg', _ICON_SIZE, color=theme.ACCENT)

        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        top_bar = QWidget()
        # #objectName-селектор: фон не каскадирует в дочерние виджеты.
        top_bar.setObjectName('topBar')
        top_bar.setStyleSheet(f"""
            QWidget#topBar {{
                background: {theme.BG_SURFACE};
                border-bottom: 1px solid {theme.BORDER};
            }}
        """)
        top_bar.setFixedHeight(56)
        tb = QHBoxLayout(top_bar)
        tb.setContentsMargins(28, 0, 28, 0)
        tb.setSpacing(12)

        tb.addWidget(_brand_widget(top_bar))
        tb.addStretch()

        # Право: действия.
        joy_btn = _icon_button('joystick.svg', 'Джойстик', top_bar)
        joy_btn.clicked.connect(on_joystick_cfg)
        logout_btn = _icon_button(None, 'Выйти', top_bar)
        logout_btn.clicked.connect(on_logout)
        tb.addWidget(joy_btn)
        tb.addWidget(logout_btn)

        # Cyan-полоска под шапкой — мягкий акцент вместо плоского border.
        line = accent_line(self)

        # Page header: eyebrow + title + subtitle.
        page_head = make_page_header(
            'Кабинет', 'Доступные дроны',
            'Выберите дрон со статусом ONLINE, чтобы запустить видеопоток.',
        )

        self._grid = _DroneGrid()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(5000)
        self._refresh_timer.timeout.connect(on_refresh)

        scroll = QScrollArea()
        scroll.setWidget(self._grid)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # Empty state: крупная блёклая иллюстрация дрона + заголовок + сабтекст.
        self._empty = QWidget()
        self._empty.setStyleSheet('background: transparent;')
        ev = QVBoxLayout(self._empty)
        ev.setAlignment(Qt.AlignCenter)
        ev.setSpacing(14)
        empty_icon = QLabel()
        empty_icon.setAlignment(Qt.AlignCenter)
        empty_icon.setPixmap(svg_pixmap('drone_list.svg', 96, color=theme.BORDER_HOVER))
        empty_icon.setStyleSheet('background: transparent;')
        empty_title = QLabel('Дроны не найдены')
        empty_title.setAlignment(Qt.AlignCenter)
        empty_title.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; background: transparent;'
            f'font-size: {theme.FONT_SIZE_LG}px; font-weight: 600;'
        )
        empty_sub = QLabel('Подключите дрон с прошивкой MavixBoard — список\nобновляется автоматически каждые 5 секунд.')
        empty_sub.setAlignment(Qt.AlignCenter)
        empty_sub.setStyleSheet(
            f'color: {theme.TEXT_MUTED}; background: transparent;'
            f'font-size: 13px;'
        )
        ev.addWidget(empty_icon)
        ev.addWidget(empty_title)
        ev.addWidget(empty_sub)
        self._empty.hide()

        root.addWidget(top_bar)
        root.addWidget(line)
        root.addWidget(page_head)
        root.addWidget(scroll, 1)
        root.addWidget(self._empty, 1)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._refresh_timer.stop()

    def update(self, drones: list):
        if not drones:
            self._empty.show()
            self._grid.hide()
            self._grid.set_cards([])
            return

        self._empty.hide()
        self._grid.show()

        cards = []
        for i, d in enumerate(drones):
            # Accept both new format ({drone_id, online}) and legacy
            # ({session_id, status}); prefer the new fields when present.
            drone_id = d.get('drone_id', d.get('session_id', ''))
            if 'online' in d:
                status = 'ready' if d.get('online') else 'offline'
            else:
                status = d.get('status', 'unknown')
            card = DroneCard(drone_id, status, i, self._icon)
            card.clicked.connect(self._on_select)
            cards.append(card)

        self._grid.set_cards(cards)
