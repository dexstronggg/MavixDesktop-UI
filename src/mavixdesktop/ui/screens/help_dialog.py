"""Окно справки: заголовок с крестиком, прокрутка, размер по родителю."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from mavixdesktop.ui.screens.help_text import as_html
from mavixdesktop.ui.screens.widgets import CloseButton
from mavixdesktop.ui.style import theme

_MARGIN = 48
_MAX_WIDTH = 900


class HelpDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Справка')
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self.setStyleSheet(f"""
            QDialog {{
                background: {theme.BG_SURFACE};
                border: 1px solid {theme.ACCENT};
                border-radius: {theme.RADIUS_LG}px;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(
            theme.SPACE_LG, theme.SPACE_MD, theme.SPACE_LG, theme.SPACE_MD
        )
        root.setSpacing(theme.SPACE_SM)
        root.addLayout(self.__build_header())
        root.addWidget(self.__build_body(), 1)

        self.__fit_to_parent()

    def __build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        title = QLabel('Справка')
        title.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; font-size: {theme.FONT_SIZE_LG}px; font-weight: 700;'
        )

        self.close_btn = CloseButton()
        self.close_btn.setToolTip('Закрыть (Esc)')
        self.close_btn.clicked.connect(self.reject)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.close_btn)
        return header

    def __build_body(self) -> QScrollArea:
        self.content = QLabel(as_html())
        self.content.setTextFormat(Qt.TextFormat.RichText)
        self.content.setWordWrap(True)
        self.content.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self.content.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.content.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; background: transparent;'
        )

        scroll = QScrollArea()
        scroll.setWidget(self.content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet('QScrollArea { background: transparent; border: none; }')
        return scroll

    def __fit_to_parent(self) -> None:
        """Размер по содержимому, но не больше окна: иначе справка уезжает за экран."""
        parent = self.parentWidget()
        available = (
            parent.size() if parent is not None else self.screen().availableSize()
        )
        max_w = min(_MAX_WIDTH, max(320, available.width() - _MARGIN))
        max_h = max(240, available.height() - _MARGIN)

        self.content.setFixedWidth(max_w - 2 * theme.SPACE_LG - 24)
        needed = self.content.sizeHint().height() + 2 * theme.SPACE_MD + 56
        self.resize(max_w, min(needed, max_h))

        if parent is not None:
            centre = parent.mapToGlobal(parent.rect().center())
            self.move(centre.x() - self.width() // 2, centre.y() - self.height() // 2)
