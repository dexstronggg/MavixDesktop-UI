"""Debug-страница для проверки отдельных функций без борта и сервера.

Включается флагом --debug при запуске (см. __main__). Сейчас содержит одну
кнопку — запуск QGroundControl, чтобы проверять поиск/диалог выбора/запуск
QGC изолированно."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mavixdesktop.ui.style import theme


class DebugPage(QWidget):
    """Стартовая страница в DEBUG-режиме: набор кнопок для ручной проверки."""

    def __init__(self, on_launch_qgc: Callable[[], None]) -> None:
        super().__init__()

        title = QLabel('Debug-режим')
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; font-size: {theme.FONT_SIZE_TITLE}px;'
            'font-weight: 700; background: transparent;'
        )

        subtitle = QLabel('Ручная проверка функций без борта и сервера')
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(
            f'color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE_SM}px;'
            'background: transparent;'
        )

        launch_btn = QPushButton('Запуск QGroundControl')
        launch_btn.setStyleSheet(theme.QSS_BUTTON_PRIMARY)
        launch_btn.setMinimumWidth(280)
        launch_btn.clicked.connect(on_launch_qgc)

        self._status = QLabel('')
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet(
            f'color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE_SM}px;'
            'background: transparent;'
        )

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(launch_btn)
        btn_row.addStretch()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            theme.SPACE_LG, theme.SPACE_LG, theme.SPACE_LG, theme.SPACE_LG
        )
        outer.setSpacing(theme.SPACE_MD)
        outer.addStretch()
        outer.addWidget(title)
        outer.addWidget(subtitle)
        outer.addSpacing(theme.SPACE_LG)
        outer.addLayout(btn_row)
        outer.addWidget(self._status)
        outer.addStretch()

    def set_status(self, text: str) -> None:
        self._status.setText(text)
