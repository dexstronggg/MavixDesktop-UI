from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtGui import QColor, QFocusEvent
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mavixdesktop.ui.screens.utils import svg_pixmap
from mavixdesktop.ui.style import theme


class TokenPage(QWidget):
    """Стартовая страница: ввод токена подключения и параметров WebRTC."""

    def __init__(self, on_connect: Callable[[str], None], cur_token: str,
                 cur_signal_url: str = '', cur_stun: str = '', cur_turn: str = '') -> None:
        super().__init__()
        self._cur_signal_url = cur_signal_url
        self._cur_stun = cur_stun
        self._cur_turn = cur_turn
        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.SPACE_LG, theme.SPACE_LG,
                                 theme.SPACE_LG, theme.SPACE_LG)

        card = self.__build_card(on_connect, cur_token)

        h_layout = QHBoxLayout()
        h_layout.addStretch()
        h_layout.addWidget(card)
        h_layout.addStretch()

        outer.addStretch()
        outer.addLayout(h_layout)
        outer.addStretch()

    def __build_card(self, on_connect: Callable[[str], None], cur_token: str) -> QWidget:
        card = QWidget()
        card.setObjectName('tokenCard')
        card.setStyleSheet(theme.QSS_TOKEN_CARD)
        card.setMinimumWidth(320)
        card.setMaximumWidth(480)
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(theme.SPACE_MD)
        card_layout.setContentsMargins(
            theme.SPACE_XL, theme.SPACE_XL,
            theme.SPACE_XL, theme.SPACE_XL,
        )

        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setPixmap(svg_pixmap('drone.svg', 80, color=theme.ACCENT))
        icon_label.setFixedHeight(88)

        title_label = QLabel('Mavix')
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY};'
            f'font-size: {theme.FONT_SIZE_TITLE}px;'
            'font-weight: 700;'
            'letter-spacing: 1px;'
        )

        sub_label = QLabel('Введите токен подключения')
        sub_label.setAlignment(Qt.AlignCenter)
        sub_label.setStyleSheet(
            f'color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE_SM}px;'
        )

        self.input = QLineEdit()
        self.input.setPlaceholderText('Connection token')
        self.input.setText(cur_token)
        self.input.setStyleSheet(theme.QSS_INPUT)
        self.input.setMinimumHeight(40)
        self.input.returnPressed.connect(lambda: on_connect(self.input.text().strip()))

        self.signal_input = QLineEdit()
        self.signal_input.setPlaceholderText('Signal server URL')
        self.signal_input.setText(self._cur_signal_url)
        self.signal_input.setStyleSheet(theme.QSS_INPUT)
        self.signal_input.setMinimumHeight(40)

        self.stun_input = QLineEdit()
        self.stun_input.setPlaceholderText('STUN server (например stun:stun.l.google.com:19302)')
        self.stun_input.setText(self._cur_stun)
        self.stun_input.setStyleSheet(theme.QSS_INPUT)
        self.stun_input.setMinimumHeight(40)

        self.turn_input = QLineEdit()
        self.turn_input.setPlaceholderText('TURN server')
        self.turn_input.setText(self._cur_turn)
        self.turn_input.setStyleSheet(theme.QSS_INPUT)
        self.turn_input.setMinimumHeight(40)

        self.__setup_focus_animation()

        connect_btn = QPushButton('Подключиться')
        connect_btn.setStyleSheet(theme.QSS_BUTTON_PRIMARY)
        connect_btn.setMinimumHeight(42)
        connect_btn.clicked.connect(lambda: on_connect(self.input.text().strip()))

        card_layout.addWidget(icon_label)
        card_layout.addSpacing(theme.SPACE_XS)
        card_layout.addWidget(title_label)
        card_layout.addWidget(sub_label)
        card_layout.addSpacing(theme.SPACE_SM)
        card_layout.addWidget(self.input)
        card_layout.addWidget(self.signal_input)
        card_layout.addWidget(self.stun_input)
        card_layout.addWidget(self.turn_input)
        card_layout.addWidget(connect_btn)

        return card

    def __setup_focus_animation(self) -> None:
        glow = QGraphicsDropShadowEffect()
        glow.setBlurRadius(0)
        glow.setColor(QColor(theme.BORDER_FOCUS))
        glow.setOffset(0, 0)
        self.input.setGraphicsEffect(glow)

        self._glow_anim = QPropertyAnimation(glow, b'blurRadius')
        self._glow_anim.setDuration(theme.ANIM_MED)
        self._glow_anim.setEasingCurve(QEasingCurve.OutCubic)

        _orig_focus_in = self.input.focusInEvent
        _orig_focus_out = self.input.focusOutEvent

        def _focus_in(event: QFocusEvent) -> None:
            self._glow_anim.stop()
            self._glow_anim.setStartValue(glow.blurRadius())
            self._glow_anim.setEndValue(20)
            self._glow_anim.start()
            _orig_focus_in(event)

        def _focus_out(event: QFocusEvent) -> None:
            self._glow_anim.stop()
            self._glow_anim.setStartValue(glow.blurRadius())
            self._glow_anim.setEndValue(0)
            self._glow_anim.start()
            _orig_focus_out(event)

        self.input.focusInEvent = _focus_in
        self.input.focusOutEvent = _focus_out
