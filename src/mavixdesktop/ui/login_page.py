"""Email + password login screen, used when no refresh token is stored.

Визуальный язык — Aviation Dark (см. Mavix Web): тёмный фон с лёгким cyan
свечением, карточка по центру, логотип сверху, поля с иконками,
full-width primary-кнопка.
"""
from __future__ import annotations

import math
import time
from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer, QPointF
from PySide6.QtGui import QFont, QPainter, QRadialGradient, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFrame, QGraphicsDropShadowEffect, QSizePolicy,
)

from mavixdesktop.ui.style import theme
from mavixdesktop.ui.screens.utils import svg_pixmap, mavix_logo_pixmap, attach_glow


class _AuthBackground(QWidget):
    """Анимированный фон страницы входа — несколько полупрозрачных
    цветовых «пятен» (cyan/blue), которые медленно плавают по
    синусоидам. Аналог bg-fx с лендинга сайта Mavix.
    """

    # Один блоб = (базовая x в %, базовая y в %, амплитуда x в %,
    # амплитуда y в %, период сек, фаза, радиус в % мин-стороны, цвет rgba).
    _BLOBS = [
        (25, 25,  18, 12, 32.0, 0.0,  55, (34, 211, 238, 36)),   # cyan
        (75, 75,  22, 14, 38.0, 1.3,  60, (6,  182, 212, 30)),   # cyan-darker
        (60, 30,  16, 18, 44.0, 2.1,  50, (29, 78,  216, 28)),   # blue
    ]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName('authBg')
        # Свой paintEvent — отключаем фоновую заливку Qt-stylesheet,
        # рисуем всё сами (стиль из родителя/QSS_GLOBAL не помешает).
        self.setAttribute(Qt.WA_StyledBackground, False)

        self._t0 = time.monotonic()
        # 30 FPS — достаточно для очень медленной анимации, нагрузка
        # минимальная (3 радиальных градиента на кадр).
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self.update)
        self._timer.start()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        # Базовая заливка фона.
        p.fillRect(self.rect(), QColor(theme.BG))

        w = self.width()
        h = self.height()
        min_side = min(w, h)
        t = time.monotonic() - self._t0

        p.setPen(Qt.NoPen)
        for bx, by, ax, ay, period, phase, rad_pct, rgba in self._BLOBS:
            # медленные перемещения по синусу/косинусу
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
    """Поле ввода с SVG-иконкой слева, скруглённое, focus-cyan."""

    def __init__(self, icon_name: str, placeholder: str, echo: bool = False,
                 parent: QWidget | None = None):
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

        # Перерисовать рамку на фокус/расфокус.
        self.input.focusInEvent = self._wrap_focus_in(self.input.focusInEvent)
        self.input.focusOutEvent = self._wrap_focus_out(self.input.focusOutEvent)

    def _wrap_focus_in(self, orig):
        def handler(event):
            self.setProperty('focused', True)
            self.style().unpolish(self)
            self.style().polish(self)
            orig(event)
        return handler

    def _wrap_focus_out(self, orig):
        def handler(event):
            self.setProperty('focused', False)
            self.style().unpolish(self)
            self.style().polish(self)
            orig(event)
        return handler


class LoginPage(QWidget):
    def __init__(self, on_login: Callable[[str, str], None]) -> None:
        super().__init__()
        self._on_login = on_login

        # Фон страницы — без него родительское окно темнит, но без свечения.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        bg = _AuthBackground(self)
        outer.addWidget(bg)

        # Центрируем карточку по обоим осям.
        center_layout = QVBoxLayout(bg)
        center_layout.setContentsMargins(24, 24, 24, 24)
        center_layout.addStretch()
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self._build_card())
        row.addStretch()
        center_layout.addLayout(row)
        center_layout.addStretch()

    # ── Card ──────────────────────────────────────────────────────────────────

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

        # ── Бренд: лого + название + сабтайтл ────────────────────────────────
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

        # Eyebrow над заголовком — как на сайте.
        eyebrow = QLabel('АВТОРИЗАЦИЯ')
        eyebrow.setAlignment(Qt.AlignCenter)
        eyebrow.setStyleSheet(theme.QSS_EYEBROW)
        layout.addWidget(eyebrow)

        title = QLabel('Вход в систему')
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; background: transparent;'
            f'font-size: {theme.FONT_SIZE_TITLE}px; font-weight: 700;'
            f'font-family: {theme.FONT_FAMILY};'
        )
        layout.addWidget(title)

        subtitle = QLabel('Войдите своим аккаунтом Mavix')
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(
            f'color: {theme.TEXT_MUTED}; background: transparent;'
            f'font-size: {theme.FONT_SIZE_SM}px;'
        )
        layout.addWidget(subtitle)

        layout.addSpacing(10)

        # ── Поля ввода ────────────────────────────────────────────────────────
        self._email_wrap = _IconLineEdit('email.svg', 'Email', echo=False)
        self.email = self._email_wrap.input
        self.email.returnPressed.connect(self._submit)
        layout.addWidget(self._email_wrap)

        self._password_wrap = _IconLineEdit('lock.svg', 'Пароль', echo=True)
        self.password = self._password_wrap.input
        self.password.returnPressed.connect(self._submit)

        # Кнопка «глаз» внутри поля пароля.
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

        # ── Ошибка (видна, только когда есть текст) ───────────────────────────
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

        # ── Submit-кнопка на всю ширину ───────────────────────────────────────
        self._submit_btn = QPushButton('Войти')
        self._submit_btn.setCursor(Qt.PointingHandCursor)
        self._submit_btn.setMinimumHeight(46)
        self._submit_btn.setStyleSheet(theme.QSS_BUTTON_PRIMARY)
        # Cyan-glow вокруг primary-кнопки — выделяет основное действие.
        attach_glow(self._submit_btn, color_hex=theme.ACCENT, radius=24, alpha=120)
        self._submit_btn.clicked.connect(self._submit)
        layout.addWidget(self._submit_btn)

        return card

    def _icon_pixmap_as_icon(self, name: str, size: int):
        from PySide6.QtGui import QIcon
        return QIcon(svg_pixmap(name, size, color=theme.TEXT_MUTED))

    # ── Public API ────────────────────────────────────────────────────────────

    def set_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.setVisible(bool(message))

    def set_busy(self, busy: bool) -> None:
        """Блокировать форму на время сетевого запроса."""
        self._submit_btn.setEnabled(not busy)
        self._submit_btn.setText('Подождите…' if busy else 'Войти')
        self.email.setEnabled(not busy)
        self.password.setEnabled(not busy)
        self._show_pw_btn.setEnabled(not busy)

    # ── Internal ──────────────────────────────────────────────────────────────

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
