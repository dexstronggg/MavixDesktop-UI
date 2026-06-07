"""Экран ожидания заявок на доставку.

После входа оператор попадает сюда: пустое состояние «ожидание заявок» и
карточки приходящих заявок (delivery_offer). По кнопке «Принять» хост
вызывает accept_delivery; при успехе открывается экран управления, при
409/delivery_taken карточка убирается.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from mavixdesktop.ui.screens.utils import svg_pixmap
from mavixdesktop.ui.style import theme


#### Карточка заявки ###################################################################
class DeliveryCard(QFrame):
    """Карточка одной заявки: адрес назначения, описание груза, кнопка «Принять»."""

    def __init__(self, delivery: dict, on_accept: Callable[[dict], None],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._delivery = delivery
        self._on_accept = on_accept
        self.setObjectName('deliveryCard')
        self.setStyleSheet(f"""
            QFrame#deliveryCard {{
                background: {theme.BG_INPUT};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS_LG}px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        title = QLabel('Новая заявка на доставку')
        title.setStyleSheet(
            f'color: {theme.ACCENT}; background: transparent;'
            f'font-size: {theme.FONT_SIZE_SM}px; font-weight: 700;'
            f'letter-spacing: 1px;'
        )
        layout.addWidget(title)

        addr = delivery.get('destination_address') or '— адрес не указан —'
        addr_lbl = QLabel(f'Куда: {addr}')
        addr_lbl.setWordWrap(True)
        addr_lbl.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; background: transparent;'
            f'font-size: {theme.FONT_SIZE_BASE}px; font-weight: 600;'
        )
        layout.addWidget(addr_lbl)

        cargo = delivery.get('cargo_description')
        if cargo:
            cargo_lbl = QLabel(f'Груз: {cargo}')
            cargo_lbl.setWordWrap(True)
            cargo_lbl.setStyleSheet(
                f'color: {theme.TEXT_MUTED}; background: transparent;'
                f'font-size: {theme.FONT_SIZE_SM}px;'
            )
            layout.addWidget(cargo_lbl)

        drone_name = delivery.get('drone_name') or delivery.get('drone_id') or '—'
        drone_lbl = QLabel(f'Дрон: {drone_name}')
        drone_lbl.setStyleSheet(
            f'color: {theme.TEXT_MUTED}; background: transparent;'
            f'font-size: {theme.FONT_SIZE_SM}px;'
            f'font-family: {theme.FONT_FAMILY_MONO};'
        )
        layout.addWidget(drone_lbl)

        layout.addSpacing(4)
        accept_btn = QPushButton('Принять')
        accept_btn.setMinimumHeight(40)
        accept_btn.setCursor(Qt.PointingHandCursor)
        accept_btn.setStyleSheet(theme.QSS_BUTTON_PRIMARY)
        accept_btn.clicked.connect(self._handle_accept)
        self._accept_btn = accept_btn
        layout.addWidget(accept_btn)

    @property
    def delivery_id(self) -> str:
        return self._delivery.get('delivery_id', '')

    def set_busy(self, busy: bool) -> None:
        self._accept_btn.setEnabled(not busy)
        self._accept_btn.setText('Принимаем…' if busy else 'Принять')

    def _handle_accept(self) -> None:
        self.set_busy(True)
        self._on_accept(self._delivery)


#### Экран ожидания заявок #############################################################
class DeliveryPage(QWidget):
    def __init__(self, on_accept: Callable[[dict], None],
                 on_logout: Callable[[], None],
                 on_open_settings: Callable[[], None] | None = None,
                 on_open_joystick: Callable[[], None] | None = None) -> None:
        super().__init__()
        self._on_accept = on_accept
        self._cards: dict[str, DeliveryCard] = {}

        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        root.addWidget(self._build_top_bar(on_logout, on_open_settings, on_open_joystick))

        self._container = QWidget()
        self._cards_layout = QVBoxLayout(self._container)
        self._cards_layout.setContentsMargins(28, 24, 28, 24)
        self._cards_layout.setSpacing(16)
        self._cards_layout.setAlignment(Qt.AlignTop)

        scroll = QScrollArea()
        scroll.setWidget(self._container)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._empty = QLabel(
            'Ожидание заявок на доставку…\n\n'
            'Когда администратор создаст заявку, она появится здесь.'
        )
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setStyleSheet(
            f'color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE_BASE}px;'
        )

        root.addWidget(scroll, 1)
        root.addWidget(self._empty, 1)
        self._refresh_empty_state()

    def _build_top_bar(self, on_logout: Callable[[], None],
                       on_open_settings: Callable[[], None] | None,
                       on_open_joystick: Callable[[], None] | None = None) -> QWidget:
        from mavixdesktop.ui.screens.drone_list_page import _brand_widget, _icon_button

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

        title = QLabel('Заявки на доставку')
        title.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; font-size: {theme.FONT_SIZE_LG}px;'
            f'font-weight: 600; background: transparent; border: none;'
            f'font-family: {theme.FONT_FAMILY};'
        )
        tb.addWidget(title)
        tb.addStretch()

        if on_open_joystick is not None:
            js_btn = QPushButton(top_bar)
            js_btn.setFixedSize(40, 38)
            js_btn.setCursor(Qt.PointingHandCursor)
            js_btn.setIcon(QIcon(svg_pixmap('joystick.svg', 18, color=theme.TEXT_MUTED)))
            js_btn.setIconSize(QSize(18, 18))
            js_btn.setToolTip('Джойстик')
            js_btn.setStyleSheet(
                f'QPushButton {{ background-color: transparent; color: {theme.TEXT_MUTED};'
                f' border: 1px solid {theme.BORDER}; border-radius: {theme.RADIUS_MD}px; }}'
                f' QPushButton:hover {{ background-color: {theme.ACCENT_SUBTLE};'
                f' color: {theme.ACCENT}; border-color: {theme.ACCENT}; }}'
            )
            js_btn.clicked.connect(on_open_joystick)
            tb.addWidget(js_btn)

        if on_open_settings is not None:
            gear_btn = QPushButton(top_bar)
            gear_btn.setFixedSize(40, 38)
            gear_btn.setCursor(Qt.PointingHandCursor)
            gear_btn.setIcon(QIcon(svg_pixmap('tune.svg', 18, color=theme.TEXT_MUTED)))
            gear_btn.setIconSize(QSize(18, 18))
            gear_btn.setToolTip('Настройки')
            gear_btn.setStyleSheet(
                f'QPushButton {{ background-color: transparent; color: {theme.TEXT_MUTED};'
                f' border: 1px solid {theme.BORDER}; border-radius: {theme.RADIUS_MD}px; }}'
                f' QPushButton:hover {{ background-color: {theme.ACCENT_SUBTLE};'
                f' color: {theme.ACCENT}; border-color: {theme.ACCENT}; }}'
            )
            gear_btn.clicked.connect(on_open_settings)
            tb.addWidget(gear_btn)

        logout_btn = _icon_button(None, 'Выйти', top_bar)
        logout_btn.clicked.connect(on_logout)
        tb.addWidget(logout_btn)
        return top_bar

    #### Публичный API #####################################################################
    def add_offer(self, delivery: dict) -> None:
        """Добавляет карточку заявки. Дубликаты по delivery_id игнорируются."""
        delivery_id = delivery.get('delivery_id')
        if not isinstance(delivery_id, str) or delivery_id in self._cards:
            return
        card = DeliveryCard(delivery, self._on_accept, self._container)
        self._cards[delivery_id] = card
        self._cards_layout.addWidget(card)
        self._refresh_empty_state()

    def remove_offer(self, delivery_id: str) -> None:
        """Убирает карточку (заявку забрали / отменили)."""
        card = self._cards.pop(delivery_id, None)
        if card is not None:
            self._cards_layout.removeWidget(card)
            card.deleteLater()
        self._refresh_empty_state()

    def set_card_busy(self, delivery_id: str, busy: bool) -> None:
        card = self._cards.get(delivery_id)
        if card is not None:
            card.set_busy(busy)

    def clear(self) -> None:
        for delivery_id in list(self._cards):
            self.remove_offer(delivery_id)

    def _refresh_empty_state(self) -> None:
        has_cards = bool(self._cards)
        self._empty.setVisible(not has_cards)
