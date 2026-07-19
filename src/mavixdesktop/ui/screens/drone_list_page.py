from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QDesktopServices,
    QHideEvent,
    QIcon,
    QMouseEvent,
    QPainter,
    QPixmap,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from mavixdesktop.core.config import settings
from mavixdesktop.ui.screens.utils import (
    AnimatedCard,
    CardGrid,
    mavix_logo_pixmap,
    svg_pixmap,
)
from mavixdesktop.ui.style import theme


def _brand_widget(parent: QWidget | None = None) -> QWidget:
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
    return w


def _icon_button(icon_name: str | None, text: str,
                 parent: QWidget | None = None) -> QPushButton:
    btn = QPushButton(text, parent)
    if icon_name is not None:
        btn.setIcon(QIcon(svg_pixmap(icon_name, 16, color=theme.TEXT_PRIMARY)))
    btn.setCursor(Qt.PointingHandCursor)
    btn.setStyleSheet(theme.QSS_BUTTON_SECONDARY)
    btn.setMinimumHeight(36)
    return btn


_CARD_W   = 210
_CARD_H   = 230
_ICON_SIZE = 88
_ID_MAX_CHARS = 16

_STATUS_COLORS = {
    'ready':      theme.STATUS_READY,
    'offline':    theme.STATUS_ERROR,
    'connecting': theme.WARNING,
}
_STATUS_LABELS = {
    'ready':      'готов',
    'offline':    'offline',
    'connecting': 'подключение',
}


def _dim_pixmap(src: QPixmap, opacity: float = 0.3) -> QPixmap:
    result = QPixmap(src.size())
    result.fill(Qt.transparent)
    p = QPainter(result)
    p.setOpacity(opacity)
    p.drawPixmap(0, 0, src)
    p.end()
    return result


def _truncate_id(drone_id: str, max_chars: int = _ID_MAX_CHARS) -> str:
    if not drone_id:
        return '——'
    if len(drone_id) <= max_chars:
        return drone_id
    head = (max_chars - 3) // 2
    tail = max_chars - 3 - head
    return f'{drone_id[:head]}…{drone_id[-tail:]}'


class DroneCard(AnimatedCard):
    clicked = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, drone_id: str, status: str, index: int,
                 icon_pixmap: QPixmap) -> None:
        super().__init__()
        self._drone_id = drone_id
        self._status = status
        self._ready = (status == 'ready')
        self._bar_color = _STATUS_COLORS.get(status, theme.ACCENT)

        self.setFixedSize(_CARD_W, _CARD_H)
        if self._ready:
            self.setCursor(Qt.PointingHandCursor)

        hover_border = self._bar_color
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
                border: 1px solid {hover_border};
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

        id_lbl = QLabel(_truncate_id(drone_id))
        id_lbl.setAlignment(Qt.AlignCenter)
        id_lbl.setStyleSheet(
            f'color: {theme.TEXT_MUTED if self._ready else theme.TEXT_DISABLED};'
            f'font-size: {theme.FONT_SIZE_SM - 1}px;'
            f'font-family: {theme.FONT_FAMILY_MONO};'
            'background: transparent; border: none;'
        )

        status_chip = QLabel(_STATUS_LABELS.get(status, status))
        status_chip.setAlignment(Qt.AlignCenter)
        chip_color = _STATUS_COLORS.get(status, theme.TEXT_MUTED)
        chip_rgba = self._hex_to_rgba(chip_color, 0.14)
        status_chip.setStyleSheet(
            f'color: {chip_color}; background: {chip_rgba};'
            f'border: 1px solid {self._hex_to_rgba(chip_color, 0.30)};'
            f'border-radius: 10px; padding: 3px 12px;'
            f'font-size: {theme.FONT_SIZE_SM - 2}px; font-weight: 500;'
        )
        status_chip.setMinimumHeight(22)

        status_wrap = QWidget()
        status_wrap.setStyleSheet('background: transparent; border: none;')
        sw = QHBoxLayout(status_wrap)
        sw.setAlignment(Qt.AlignCenter)
        sw.setContentsMargins(0, 0, 0, 0)
        sw.addWidget(status_chip)

        layout.addWidget(icon_lbl)
        layout.addWidget(name_lbl)
        layout.addWidget(id_lbl)
        layout.addWidget(status_wrap)

        self._dots_btn = QPushButton(self)
        self._dots_btn.setFixedSize(28, 28)
        self._dots_btn.setCursor(Qt.PointingHandCursor)
        self._dots_btn.setIcon(QIcon(svg_pixmap('three_dots.svg', 16, color=theme.TEXT_MUTED)))
        self._dots_btn.setIconSize(QSize(16, 16))
        self._dots_btn.setToolTip('Действия')
        self._dots_btn.setStyleSheet(
            'QPushButton { background: transparent; border: none; border-radius: 14px; }'
            f' QPushButton:hover {{ background: {theme.BG_HOVER}; }}'
        )
        self._dots_btn.clicked.connect(self._show_menu)
        self._dots_btn.move(_CARD_W - 28 - 8, 8)
        self._dots_btn.raise_()

    def _show_menu(self) -> None:
        menu = QMenu(self)
        delete_act = QAction('Удалить дрон', menu)
        delete_act.triggered.connect(self._confirm_delete)
        menu.addAction(delete_act)
        pos = self._dots_btn.mapToGlobal(self._dots_btn.rect().bottomRight())
        menu.exec(pos)

    def _confirm_delete(self) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle('Удалить дрон?')
        box.setText(
            'Дрон будет полностью удалён с сервера. Он исчезнет из вашего '
            'списка и перестанет принимать команды.'
        )
        box.setInformativeText(
            'Чтобы добавить его обратно, потребуется заново скачать '
            'установщик MavixBoard со страницы «Программы» и переустановить '
            'на Raspberry Pi — старый токен после удаления станет невалидным.'
        )
        delete_btn = box.addButton('Удалить', QMessageBox.DestructiveRole)
        cancel_btn = box.addButton('Отмена', QMessageBox.RejectRole)
        box.setDefaultButton(cancel_btn)
        box.exec()
        if box.clickedButton() is delete_btn:
            self.delete_requested.emit(self._drone_id)

    @staticmethod
    def _hex_to_rgba(hex_color: str, alpha: float) -> str:
        h = hex_color.lstrip('#')
        if len(h) != 6:
            return hex_color
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
        return f'rgba({r},{g},{b},{alpha})'

    def _on_hover(self, hovered: bool) -> None:
        effective = hovered and self._ready
        self.setStyleSheet(self._style_hover if effective else self._style_normal)
        self._animate_bar(1000 if effective else 0)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._ready and event.button() == Qt.LeftButton:
            self.clicked.emit(self._drone_id)
        super().mousePressEvent(event)


class _DroneGrid(CardGrid):
    CARD_W = _CARD_W
    CARD_H = _CARD_H
    GAP    = 20


class _StatsBar(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName('statsBar')
        self.setFixedHeight(56)
        self.setStyleSheet(f"""
            QWidget#statsBar {{
                background: transparent;
                border-bottom: 1px solid {theme.BORDER};
            }}
        """)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(28, 0, 28, 0)
        lay.setSpacing(0)

        self._items: dict[str, tuple[QLabel, QLabel]] = {}
        for key, label, color in [
            ('total',      'всего',       theme.TEXT_PRIMARY),
            ('ready',      'готов',       _STATUS_COLORS['ready']),
            ('offline',    'offline',     _STATUS_COLORS['offline']),
            ('connecting', 'подключение', _STATUS_COLORS['connecting']),
        ]:
            block = self._build_item(label, color)
            lay.addWidget(block)
            if key != 'connecting':
                sep = QFrame()
                sep.setFixedSize(1, 22)
                sep.setStyleSheet(f'background: {theme.BORDER}; border: none;')
                lay.addSpacing(20)
                lay.addWidget(sep)
                lay.addSpacing(20)
        lay.addStretch()

    def _build_item(self, label_text: str, color: str) -> QWidget:
        wrap = QWidget()
        wrap.setStyleSheet('background: transparent;')
        h = QHBoxLayout(wrap)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        value = QLabel('0')
        value.setStyleSheet(
            f'color: {color}; background: transparent; border: none;'
            f'font-size: {theme.FONT_SIZE_LG}px; font-weight: 700;'
            f'font-family: {theme.FONT_FAMILY_MONO};'
        )

        caption = QLabel(label_text)
        caption.setStyleSheet(
            f'color: {theme.TEXT_MUTED}; background: transparent; border: none;'
            f'font-size: {theme.FONT_SIZE_SM}px;'
        )

        h.addWidget(value)
        h.addWidget(caption)
        self._items[label_text] = (value, caption)
        return wrap

    def set_counts(self, total: int, ready: int, offline: int, connecting: int) -> None:
        for label, count in [
            ('всего', total),
            ('готов', ready),
            ('offline', offline),
            ('подключение', connecting),
        ]:
            self._items[label][0].setText(str(count))


class _DocsHint(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName('docsHint')
        self.setFixedHeight(72)
        self.setStyleSheet(f"""
            QWidget#docsHint {{
                background: {theme.BG_SURFACE};
                border-top: 1px solid {theme.BORDER};
            }}
            QWidget#docsHint QLabel {{
                background: transparent;
            }}
        """)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(28, 0, 28, 0)
        lay.setSpacing(14)
        lay.addStretch()

        icon = QLabel()
        icon.setFixedSize(24, 24)
        icon.setPixmap(svg_pixmap('drone_list.svg', 24, color=theme.TEXT_MUTED))
        lay.addWidget(icon)

        title = QLabel('Не видите свой дрон?')
        title.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; font-size: {theme.FONT_SIZE_SM}px;'
            'font-weight: 600;'
        )
        lay.addWidget(title)

        sep = QLabel('·')
        sep.setStyleSheet(f'color: {theme.TEXT_DISABLED}; font-size: {theme.FONT_SIZE_BASE}px;')
        lay.addWidget(sep)

        link = QLabel('Как зарегистрировать дрон — см. документацию')
        link.setCursor(Qt.PointingHandCursor)
        link.setStyleSheet(
            f'color: {theme.ACCENT}; font-size: {theme.FONT_SIZE_SM}px;'
            f'text-decoration: underline;'
        )
        link.mousePressEvent = self._open_docs
        lay.addWidget(link)

        lay.addStretch()

    def _open_docs(self, _event: QMouseEvent) -> None:
        base = settings.http_url.rstrip('/')
        QDesktopServices.openUrl(QUrl(f'{base}/dashboard/docs/user'))


class DroneListPage(QWidget):
    def __init__(self, on_select: Callable[[str], None], on_refresh: Callable[[], None],
                 on_logout: Callable[[], None], on_joystick_cfg: Callable[[], None],
                 on_open_settings: Callable[[], None] | None = None,
                 on_delete_drone: Callable[[str], None] | None = None) -> None:
        super().__init__()
        self._on_select = on_select
        self._on_delete_drone = on_delete_drone
        self._icon = svg_pixmap('drone_list.svg', _ICON_SIZE, color=theme.ACCENT)

        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        top_bar = QWidget()
        top_bar.setObjectName('topBar')
        top_bar.setStyleSheet(f"""
            QWidget#topBar {{
                background: {theme.BG_SURFACE};
                border-bottom: 1px solid {theme.BORDER};
            }}
        """)
        top_bar.setFixedHeight(64)
        tb = QHBoxLayout(top_bar)
        tb.setContentsMargins(28, 0, 28, 0)
        tb.setSpacing(12)

        tb.addWidget(_brand_widget(top_bar))
        sep = QFrame()
        sep.setFixedSize(1, 22)
        sep.setStyleSheet(f'background: {theme.BORDER}; border: none;')
        tb.addSpacing(8)
        tb.addWidget(sep)
        tb.addSpacing(8)

        title = QLabel('Доступные дроны')
        title.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; font-size: {theme.FONT_SIZE_LG}px;'
            f'font-weight: 600; background: transparent; border: none;'
            f'font-family: {theme.FONT_FAMILY};'
        )
        tb.addWidget(title)
        tb.addStretch()

        joy_btn = _icon_button('joystick.svg', 'Джойстик', top_bar)
        joy_btn.clicked.connect(on_joystick_cfg)

        gear_btn = QPushButton(top_bar)
        gear_btn.setFixedSize(40, 38)
        gear_btn.setCursor(Qt.PointingHandCursor)
        gear_btn.setIcon(QIcon(svg_pixmap('tune.svg', 18, color=theme.TEXT_MUTED)))
        gear_btn.setIconSize(QSize(18, 18))
        gear_btn.setToolTip('Настройки')
        gear_btn.setStyleSheet(
            f'QPushButton {{'
            f' background-color: transparent;'
            f' color: {theme.TEXT_MUTED};'
            f' border: 1px solid {theme.BORDER};'
            f' border-radius: {theme.RADIUS_MD}px;'
            f' }}'
            f' QPushButton:hover {{'
            f' background-color: {theme.ACCENT_SUBTLE};'
            f' color: {theme.ACCENT};'
            f' border-color: {theme.ACCENT};'
            f' }}'
        )
        if on_open_settings is not None:
            gear_btn.clicked.connect(on_open_settings)

        logout_btn = _icon_button(None, 'Выйти', top_bar)
        logout_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {theme.TEXT_MUTED};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS_MD}px;
                padding: 8px 16px;
                font-size: {theme.FONT_SIZE_SM}px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: rgba(248, 113, 113, 0.12);
                color: {theme.STATUS_ERROR};
            }}
            QPushButton:pressed {{
                background-color: rgba(248, 113, 113, 0.20);
                color: {theme.STATUS_ERROR};
            }}
        """)
        logout_btn.clicked.connect(on_logout)

        tb.addWidget(joy_btn)
        tb.addWidget(gear_btn)
        tb.addWidget(logout_btn)

        self._stats = _StatsBar()
        self._grid = _DroneGrid()
        self._hint = _DocsHint()

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
        root.addWidget(self._stats)
        root.addWidget(scroll, 1)
        root.addWidget(self._empty, 1)
        root.addWidget(self._hint)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._refresh_timer.start()

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        self._refresh_timer.stop()

    def update(self, drones: list) -> None:
        if not drones:
            self._stats.set_counts(0, 0, 0, 0)
            self._empty.show()
            self._grid.hide()
            self._grid.set_cards([])
            return

        self._empty.hide()
        self._grid.show()

        cards = []
        counts = {'ready': 0, 'offline': 0, 'connecting': 0}
        for i, d in enumerate(drones):
            drone_id = d.get('drone_id', d.get('session_id', ''))
            if 'online' in d:
                status = 'ready' if d.get('online') else 'offline'
            else:
                status = d.get('status', 'unknown')
            if status in counts:
                counts[status] += 1
            card = DroneCard(drone_id, status, i, self._icon)
            card.clicked.connect(self._on_select)
            if self._on_delete_drone is not None:
                card.delete_requested.connect(self._on_delete_drone)
            cards.append(card)

        self._stats.set_counts(
            total=len(drones),
            ready=counts['ready'],
            offline=counts['offline'],
            connecting=counts['connecting'],
        )
        self._grid.set_cards(cards)
