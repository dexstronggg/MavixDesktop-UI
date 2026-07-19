"""Login screen with email and password."""
from __future__ import annotations

import math
import time
from collections.abc import Callable

from PySide6.QtCore import QPointF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mavixdesktop.ui.screens.utils import mavix_logo_pixmap, svg_pixmap
from mavixdesktop.ui.style import theme


class _AuthBackground(QWidget):
    _BLOBS = [
        (25, 25,  18, 12, 32.0, 0.0,  55, (34, 211, 238, 36)),
        (75, 75,  22, 14, 38.0, 1.3,  60, (6,  182, 212, 30)),
        (60, 30,  16, 18, 44.0, 2.1,  50, (29, 78,  216, 28)),
    ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName('authBg')
        self.setAttribute(Qt.WA_StyledBackground, False)

        self._t0 = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self.update)
        self._timer.start()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        p.fillRect(self.rect(), QColor(theme.BG))

        w = self.width()
        h = self.height()
        min_side = min(w, h)
        t = time.monotonic() - self._t0

        p.setPen(Qt.NoPen)
        for bx, by, ax, ay, period, phase, rad_pct, rgba in self._BLOBS:
            cx = (bx + ax * math.sin(2 * math.pi * t / period + phase)) / 100.0 * w
            cy = (by + ay * math.cos(2 * math.pi * t / period + phase * 1.2)) / 100.0 * h
            radius = rad_pct / 100.0 * min_side

            grad = QRadialGradient(QPointF(cx, cy), radius)
            grad.setColorAt(0.0, QColor(*rgba))
            grad.setColorAt(1.0, QColor(rgba[0], rgba[1], rgba[2], 0))
            p.setBrush(grad)
            p.drawEllipse(QPointF(cx, cy), radius, radius)

        p.end()


class _IconLineEdit(QFrame):
    def __init__(self, icon_name: str, placeholder: str, echo: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName('iconInput')
        self.setMinimumHeight(44)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._normal_qss = f"""
            QFrame#iconInput {{
                background: {theme.BG_INPUT};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS_MD}px;
            }}
            QFrame#iconInput[focused="true"] {{
                border: 1px solid {theme.ACCENT};
            }}
            QLineEdit {{
                background: transparent;
                border: none;
                color: {theme.TEXT_PRIMARY};
                font-size: {theme.FONT_SIZE_BASE}px;
                font-family: {theme.FONT_FAMILY};
                padding: 0;
                selection-background-color: {theme.ACCENT};
                selection-color: {theme.BG};
            }}
            QLabel {{
                background: transparent;
                color: {theme.TEXT_MUTED};
            }}
            QPushButton {{
                background: transparent;
                border: none;
                color: {theme.TEXT_MUTED};
                padding: 0 8px;
            }}
            QPushButton:hover {{
                color: {theme.ACCENT};
            }}
        """
        self.setStyleSheet(self._normal_qss)
        self.setProperty('focused', False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 8, 0)
        layout.setSpacing(10)

        self._icon = QLabel()
        self._icon.setFixedSize(18, 18)
        self._icon.setPixmap(svg_pixmap(icon_name, 18, color=theme.TEXT_MUTED))
        self._icon.setStyleSheet('background: transparent;')
        layout.addWidget(self._icon)

        self.input = QLineEdit()
        self.input.setPlaceholderText(placeholder)
        if echo:
            self.input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.input, 1)

        self.input.focusInEvent = self._wrap_focus_in(self.input.focusInEvent)
        self.input.focusOutEvent = self._wrap_focus_out(self.input.focusOutEvent)

    def _wrap_focus_in(self, orig):
        def handler(event) -> None:
            self.setProperty('focused', True)
            self.style().unpolish(self)
            self.style().polish(self)
            orig(event)
        return handler

    def _wrap_focus_out(self, orig):
        def handler(event) -> None:
            self.setProperty('focused', False)
            self.style().unpolish(self)
            self.style().polish(self)
            orig(event)
        return handler


class _Spinner(QWidget):
    def __init__(self, size: int = 16, color: QColor | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._size = size
        self._color = color or QColor(theme.BG)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.hide()

    def start(self) -> None:
        self._timer.start()
        self.show()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def _tick(self) -> None:
        self._angle = (self._angle + 8) % 360
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(self._color, 2)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        rect = self.rect().adjusted(2, 2, -2, -2)
        p.drawArc(rect, -self._angle * 16, 270 * 16)
        p.end()


class LoginPage(QWidget):
    def __init__(
        self,
        on_login: Callable[[str, str], None],
        on_forgot_password: Callable[[str], None] | None = None,
        on_open_settings: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._on_login = on_login
        self._on_forgot_password = on_forgot_password
        self._on_open_settings = on_open_settings

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        bg = _AuthBackground(self)
        outer.addWidget(bg)

        center_layout = QVBoxLayout(bg)
        center_layout.setContentsMargins(24, 24, 24, 24)
        center_layout.addLayout(self._build_top_bar())
        center_layout.addStretch()
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self._build_card())
        row.addStretch()
        center_layout.addLayout(row)
        center_layout.addStretch()

    def _build_top_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.addStretch()
        gear = QPushButton()
        gear.setFixedSize(36, 36)
        gear.setCursor(Qt.PointingHandCursor)
        gear.setIcon(QIcon(svg_pixmap('tune.svg', 20, color=theme.TEXT_MUTED)))
        gear.setIconSize(QSize(20, 20))
        gear.setToolTip('Настройки')
        gear.setStyleSheet(
            f'QPushButton {{'
            f' background-color: transparent;'
            f' border: 1px solid {theme.BORDER};'
            f' border-radius: 18px;'
            f' }}'
            f' QPushButton:hover {{'
            f' background-color: {theme.ACCENT_SUBTLE};'
            f' border-color: {theme.ACCENT};'
            f' }}'
        )
        if self._on_open_settings is not None:
            gear.clicked.connect(self._on_open_settings)
        bar.addWidget(gear)
        return bar

    def _build_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName('authCard')
        card.setFixedWidth(420)
        card.setStyleSheet(f"""
            QFrame#authCard {{
                background: {theme.BG_INPUT};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS_LG}px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(0, 0, 0, 140))
        card.setGraphicsEffect(shadow)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(18)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        brand_row.setContentsMargins(0, 0, 0, 0)
        brand_row.addStretch()

        logo = QLabel()
        logo.setFixedSize(36, 36)
        logo.setPixmap(mavix_logo_pixmap(36))
        logo.setStyleSheet('background: transparent;')
        brand_row.addWidget(logo)

        wordmark = QLabel('MAVIX')
        wordmark.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; background: transparent;'
            f'font-family: {theme.FONT_FAMILY_MONO}; font-weight: 600;'
            f'font-size: {theme.FONT_SIZE_LG}px; letter-spacing: 3px;'
        )
        brand_row.addWidget(wordmark)
        brand_row.addStretch()
        layout.addLayout(brand_row)

        title = QLabel('Вход в систему')
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; background: transparent;'
            f'font-size: {theme.FONT_SIZE_TITLE}px; font-weight: 700;'
            f'font-family: {theme.FONT_FAMILY};'
        )
        layout.addWidget(title)

        subtitle = QLabel('Введите данные вашего аккаунта')
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(
            f'color: {theme.TEXT_MUTED}; background: transparent;'
            f'font-size: {theme.FONT_SIZE_SM}px;'
        )
        layout.addWidget(subtitle)

        layout.addSpacing(10)

        self._email_wrap = _IconLineEdit('email.svg', 'Email', echo=False)
        self.email = self._email_wrap.input
        self.email.returnPressed.connect(self._submit)
        layout.addWidget(self._email_wrap)

        self._password_wrap = _IconLineEdit('lock.svg', 'Пароль', echo=True)
        self.password = self._password_wrap.input
        self.password.returnPressed.connect(self._submit)

        self._show_pw_btn = QPushButton()
        self._show_pw_btn.setIcon(self._icon_pixmap_as_icon('eye.svg', 18))
        self._show_pw_btn.setFixedSize(30, 30)
        self._show_pw_btn.setCheckable(True)
        self._show_pw_btn.setCursor(Qt.PointingHandCursor)
        self._show_pw_btn.setToolTip('Показать пароль')
        self._show_pw_btn.setFocusPolicy(Qt.NoFocus)
        self._show_pw_btn.setStyleSheet(theme.QSS_BUTTON_ICON)
        self._show_pw_btn.toggled.connect(self._toggle_password_visibility)
        self._password_wrap.layout().addWidget(self._show_pw_btn)
        layout.addWidget(self._password_wrap)

        self.error = QLabel('')
        self.error.setWordWrap(True)
        self.error.setStyleSheet(
            f'color: {theme.STATUS_ERROR}; background: rgba(248,113,113,0.10);'
            f'border: 1px solid rgba(248,113,113,0.30);'
            f'border-radius: {theme.RADIUS_SM}px;'
            f'padding: 8px 12px;'
            f'font-size: {theme.FONT_SIZE_SM}px;'
        )
        self.error.hide()
        layout.addWidget(self.error)

        self._submit_btn = QPushButton('Войти')
        self._submit_btn.setCursor(Qt.PointingHandCursor)
        self._submit_btn.setMinimumHeight(46)
        self._submit_btn.setStyleSheet(theme.QSS_BUTTON_PRIMARY)
        self._submit_btn.clicked.connect(self._submit)
        layout.addWidget(self._submit_btn)

        self._busy_spinner = _Spinner(16, QColor(theme.BG), self._submit_btn)
        self._submit_btn.installEventFilter(self)

        forgot_row = QHBoxLayout()
        forgot_row.setContentsMargins(0, 4, 0, 0)
        forgot_row.addStretch()
        self._forgot_link = QLabel('Забыли пароль?')
        self._forgot_link.setCursor(Qt.PointingHandCursor)
        self._forgot_link.setStyleSheet(
            f'color: {theme.TEXT_MUTED}; background: transparent;'
            f'font-size: {theme.FONT_SIZE_SM}px;'
        )
        self._forgot_link.mousePressEvent = self._on_forgot_clicked
        forgot_row.addWidget(self._forgot_link)
        forgot_row.addStretch()
        layout.addLayout(forgot_row)

        self._forgot_msg = QLabel('')
        self._forgot_msg.setAlignment(Qt.AlignCenter)
        self._forgot_msg.setWordWrap(True)
        self._forgot_msg.setStyleSheet(
            f'color: {theme.ACCENT}; background: transparent;'
            f'font-size: {theme.FONT_SIZE_SM - 1}px; padding: 4px 0;'
        )
        self._forgot_msg.hide()
        layout.addWidget(self._forgot_msg)

        return card

    def eventFilter(self, obj, event) -> bool:
        if obj is self._submit_btn:
            from PySide6.QtCore import QEvent as _QE
            if event.type() in (_QE.Resize, _QE.Show):
                btn_h = self._submit_btn.height()
                self._busy_spinner.move(18, (btn_h - self._busy_spinner.height()) // 2)
        return False

    def _icon_pixmap_as_icon(self, name: str, size: int) -> QIcon:
        return QIcon(svg_pixmap(name, size, color=theme.TEXT_MUTED))

    def set_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.setVisible(bool(message))

    def reset(self) -> None:
        self.email.clear()
        self.password.clear()
        self.set_error('')
        self._forgot_msg.hide()
        self._forgot_msg.clear()
        self.set_busy(False)
        self.email.setFocus()

    def set_busy(self, busy: bool) -> None:
        self._submit_btn.setEnabled(not busy)
        if busy:
            self._submit_btn.setText('     Подождите…')
            self._busy_spinner.start()
            self._busy_spinner.raise_()
        else:
            self._submit_btn.setText('Войти')
            self._busy_spinner.stop()
        self.email.setEnabled(not busy)
        self.password.setEnabled(not busy)
        self._show_pw_btn.setEnabled(not busy)
        self._forgot_link.setEnabled(not busy)

    def _on_forgot_clicked(self, _event) -> None:
        if not self._submit_btn.isEnabled():
            return
        email = self.email.text().strip()
        if not email or '@' not in email:
            self._forgot_msg.setStyleSheet(
                f'color: {theme.STATUS_ERROR}; background: transparent;'
                f'font-size: {theme.FONT_SIZE_SM - 1}px; padding: 4px 0;'
            )
            self._forgot_msg.setText('Введите email в поле выше и нажмите ссылку ещё раз')
            self._forgot_msg.show()
            return
        if self._on_forgot_password is not None:
            self._on_forgot_password(email)
        self._forgot_msg.setStyleSheet(
            f'color: {theme.ACCENT}; background: transparent;'
            f'font-size: {theme.FONT_SIZE_SM - 1}px; padding: 4px 0;'
        )
        self._forgot_msg.setText(
            'Инструкции по восстановлению отправлены на вашу почту.'
        )
        self._forgot_msg.show()

    def _toggle_password_visibility(self, visible: bool) -> None:
        self.password.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )
        self._show_pw_btn.setToolTip('Скрыть пароль' if visible else 'Показать пароль')

    def _submit(self) -> None:
        if not self._submit_btn.isEnabled():
            return
        email = self.email.text().strip()
        pw = self.password.text()
        if not email or not pw:
            self.set_error('Email и пароль обязательны')
            return
        self.set_error('')
        self._on_login(email, pw)
