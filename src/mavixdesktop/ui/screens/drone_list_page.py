from typing import Callable

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QPixmap, QPainter, QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame,
)

from mavixdesktop.ui.style import theme
from .utils import svg_pixmap, AnimatedCard, CardGrid


def _brand_widget(parent: QWidget | None = None) -> QWidget:
    """Логотип-бренд: квадратик с M + надпись MAVIX, как в шапке сайта."""
    w = QWidget(parent)
    w.setStyleSheet('background: transparent;')
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(10)
    logo = QLabel()
    logo.setFixedSize(28, 28)
    logo.setPixmap(svg_pixmap('mavix_logo.svg', 28))
    logo.setStyleSheet('background: transparent;')
    h.addWidget(logo)
    wordmark = QLabel('MAVIX')
    wordmark.setStyleSheet(
        f'background: transparent; color: {theme.TEXT_PRIMARY};'
        f'font-family: {theme.FONT_FAMILY_MONO}; font-weight: 600;'
        f'font-size: {theme.FONT_SIZE_BASE}px; letter-spacing: 2px;'
    )
    h.addWidget(wordmark)
    return w


def _icon_button(icon_name: str, text: str, parent: QWidget | None = None) -> QPushButton:
    """Кнопка с SVG-иконкой + текстом, в ghost-стиле."""
    btn = QPushButton(text, parent)
    btn.setIcon(QIcon(svg_pixmap(icon_name, 16)))
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

        status_row = QWidget()
        status_row.setStyleSheet('background: transparent; border: none;')
        sr_layout = QHBoxLayout(status_row)
        sr_layout.setAlignment(Qt.AlignCenter)
        sr_layout.setSpacing(6)
        sr_layout.setContentsMargins(0, 0, 0, 0)

        dot = QLabel('●')
        dot.setStyleSheet(
            f'color: {theme.STATUS_READY if self._ready else theme.STATUS_ERROR}; font-size: 11px;'
            'background: transparent; border: none;'
        )
        status_lbl = QLabel('готов' if self._ready else status)
        status_lbl.setStyleSheet(
            f'color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE_SM - 3}px;'
            'background: transparent; border: none;'
        )
        sr_layout.addWidget(dot)
        sr_layout.addWidget(status_lbl)

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


class _DroneGrid(CardGrid):
    CARD_W = _CARD_W
    CARD_H = _CARD_H
    GAP    = 20


class DroneListPage(QWidget):
    def __init__(self, on_select: Callable, on_refresh: Callable,
                 on_logout: Callable, on_joystick_cfg: Callable):
        super().__init__()
        self._on_select = on_select
        self._icon = svg_pixmap('drone_list.svg', _ICON_SIZE)

        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        top_bar = QWidget()
        top_bar.setStyleSheet(
            f'background: {theme.BG_SURFACE}; border-bottom: 1px solid {theme.BORDER};'
        )
        top_bar.setFixedHeight(64)
        tb = QHBoxLayout(top_bar)
        tb.setContentsMargins(28, 0, 28, 0)
        tb.setSpacing(12)

        # Лево: лого-бренд + заголовок раздела.
        tb.addWidget(_brand_widget(top_bar))
        sep = QFrame()
        sep.setFixedSize(1, 22)
        sep.setStyleSheet(f'background: {theme.BORDER}; border: none;')
        tb.addSpacing(8)
        tb.addWidget(sep)
        tb.addSpacing(8)

        title = QLabel('Дроны')
        title.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; font-size: {theme.FONT_SIZE_LG}px;'
            f'font-weight: 600; background: transparent; border: none;'
            f'font-family: {theme.FONT_FAMILY};'
        )
        tb.addWidget(title)
        tb.addStretch()

        # Право: действия.
        joy_btn = _icon_button('joystick.svg', 'Джойстик', top_bar)
        joy_btn.clicked.connect(on_joystick_cfg)

        logout_btn = _icon_button('logout.svg', 'Выйти', top_bar)
        logout_btn.clicked.connect(on_logout)

        tb.addWidget(joy_btn)
        tb.addWidget(logout_btn)

        self._grid = _DroneGrid()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(5000)
        self._refresh_timer.timeout.connect(on_refresh)

        scroll = QScrollArea()
        scroll.setWidget(self._grid)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._empty = QLabel('Дроны не найдены\n\nПодождите, список обновляется автоматически')
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setStyleSheet(
            f'color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE_BASE}px;'
        )
        self._empty.hide()

        root.addWidget(top_bar)
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
