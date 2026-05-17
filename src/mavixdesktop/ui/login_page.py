"""Email + password login screen, used when no refresh token is stored."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
)


class LoginPage(QWidget):
    def __init__(self, on_login: Callable[[str, str], None]) -> None:
        super().__init__()
        self._on_login = on_login
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 48, 48, 48)
        root.addStretch()

        title = QLabel('Sign in to Mavix')
        title.setStyleSheet('font-size: 20px;')
        root.addWidget(title)

        self.email = QLineEdit()
        self.email.setPlaceholderText('email')
        self.email.returnPressed.connect(self._submit)
        root.addWidget(self.email)

        # Поле пароля + кнопка-«глаз» для переключения видимости
        pw_row = QHBoxLayout()
        pw_row.setSpacing(6)
        self.password = QLineEdit()
        self.password.setPlaceholderText('password')
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.returnPressed.connect(self._submit)
        pw_row.addWidget(self.password, 1)

        self._show_pw_btn = QPushButton('👁')
        self._show_pw_btn.setCheckable(True)
        self._show_pw_btn.setFixedWidth(36)
        self._show_pw_btn.setToolTip('Показать пароль')
        self._show_pw_btn.setFocusPolicy(Qt.NoFocus)
        self._show_pw_btn.toggled.connect(self._toggle_password_visibility)
        pw_row.addWidget(self._show_pw_btn)
        root.addLayout(pw_row)

        self.error = QLabel('')
        self.error.setStyleSheet('color: #e57373;')
        self.error.setWordWrap(True)
        root.addWidget(self.error)

        row = QHBoxLayout()
        row.addStretch()
        self._submit_btn = QPushButton('Sign in')
        self._submit_btn.clicked.connect(self._submit)
        row.addWidget(self._submit_btn)
        root.addLayout(row)
        root.addStretch()

    # ── Public API ────────────────────────────────────────────────────────────

    def set_error(self, message: str) -> None:
        self.error.setText(message)

    def set_busy(self, busy: bool) -> None:
        """Блокировать форму на время сетевого запроса."""
        self._submit_btn.setEnabled(not busy)
        self._submit_btn.setText('Подождите…' if busy else 'Sign in')
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
            self.error.setText('email и пароль обязательны')
            return
        self.error.setText('')
        self._on_login(email, pw)
