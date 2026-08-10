"""Shared UI utilities for the screens package."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QEvent,
    QPropertyAnimation,
    QSize,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPaintEvent,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QLayoutItem,
    QPushButton,
    QScrollArea,
    QWidget,
)

from mavixdesktop.ui.style import theme

_ICONS_DIR = Path(__file__).parent.parent / 'icons'


def svg_pixmap(name: str, size: int, color: str | None = None) -> QPixmap:
    renderer = QSvgRenderer(str(_ICONS_DIR / name))
    px = QPixmap(QSize(size, size))
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    renderer.render(p)
    if color is not None:
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        p.fillRect(px.rect(), QColor(color))
    p.end()
    return px


def mavix_logo_pixmap(size: int) -> QPixmap:
    px = QPixmap(QSize(size, size))
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0.0, QColor('#22d3ee'))
    grad.setColorAt(1.0, QColor('#06b6d4'))
    p.setBrush(grad)
    p.setPen(Qt.PenStyle.NoPen)
    radius = size * 0.26
    p.drawRoundedRect(0, 0, size, size, radius, radius)

    font = QFont('Inter')
    font.setPixelSize(int(size * 0.62))
    font.setWeight(QFont.Weight.Bold)
    p.setFont(font)
    p.setPen(QColor('#001017'))
    p.drawText(0, 0, size, size, Qt.AlignmentFlag.AlignCenter, 'M')
    p.end()
    return px


def overlay_btn(text: str, parent: QWidget, size: int | None = None) -> QPushButton:
    if size is None:
        size = theme.OVERLAY_BTN_SIDE
    btn = QPushButton(text, parent)
    btn.setFixedSize(size, size)
    # иначе кнопка забирает фокус: пробел «нажимает» её, а стрелки уходят на
    # навигацию по фокусу и не доходят до keyPressEvent окна
    btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    btn.setFlat(True)
    btn.setAutoFillBackground(False)
    btn.setStyleSheet(f"""
        QPushButton {{
            background: transparent;
            color: {theme.TEXT_PRIMARY};
            border: none;
            border-radius: {size // 2}px;
            font-size: {theme.OVERLAY_BTN_SIDE_FONT}px;
        }}
        QPushButton:hover {{
            background: rgba(42, 130, 218, 0.20);
        }}
        QPushButton:pressed {{
            background: rgba(42, 130, 218, 0.32);
        }}
        QPushButton:disabled {{
            color: rgba(255,255,255,0.20);
            background: transparent;
        }}
    """)
    return btn


def overlay_icon_btn(
    svg_name: str,
    parent: QWidget,
    size: int | None = None,
    icon_size: int | None = None,
) -> QPushButton:
    if size is None:
        size = theme.OVERLAY_BTN_CORNER
    if icon_size is None:
        icon_size = theme.OVERLAY_BTN_CORNER_ICON
    btn = QPushButton(parent)
    btn.setFixedSize(size, size)
    btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    btn.setIcon(QIcon(svg_pixmap(svg_name, icon_size, color=theme.TEXT_PRIMARY)))
    btn.setIconSize(QSize(icon_size, icon_size))
    btn.setFlat(True)
    btn.setAutoFillBackground(False)
    btn.setStyleSheet(f"""
        QPushButton {{
            background: transparent;
            border: none;
            border-radius: {size // 2}px;
        }}
        QPushButton:hover {{
            background: rgba(42, 130, 218, 0.20);
        }}
        QPushButton:pressed {{
            background: rgba(42, 130, 218, 0.32);
        }}
        QPushButton:disabled {{
            background: transparent;
        }}
    """)
    return btn


class AnimatedCard(QWidget):
    _ANIM_DURATION = 500
    _BAR_RADIUS = theme.RADIUS_LG
    _BAR_HEIGHT = 3

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._bar_progress = 0
        self._bar_color: str = theme.ACCENT
        self._bar_anim = QPropertyAnimation(self, b'bar_progress')
        self._bar_anim.setDuration(self._ANIM_DURATION)
        self._bar_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    @Property(int)
    def bar_progress(self) -> int:
        return self._bar_progress

    @bar_progress.setter  # type: ignore[no-redef]
    def bar_progress(self, value: int) -> None:
        self._bar_progress = value
        self.update()

    def event(self, e: QEvent) -> bool:
        if e.type() == QEvent.Type.HoverEnter:
            self._on_hover(True)
        elif e.type() == QEvent.Type.HoverLeave:
            self._on_hover(False)
        return super().event(e)

    def _on_hover(self, hovered: bool) -> None:
        self._animate_bar(1000 if hovered else 0)

    def _animate_bar(self, target: int) -> None:
        self._bar_anim.stop()
        self._bar_anim.setStartValue(self._bar_progress)
        self._bar_anim.setEndValue(target)
        self._bar_anim.start()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if self._bar_progress <= 0:
            return
        r = self._BAR_RADIUS
        bar_max_w = self.width() - 2 * r
        bar_w = max(0, int(self._bar_progress * bar_max_w / 1000))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._bar_color))
        painter.drawRoundedRect(
            r, self.height() - self._BAR_HEIGHT, bar_w, self._BAR_HEIGHT, 1, 1
        )
        painter.end()


class CardGrid(QWidget):
    CARD_W: int = 0
    CARD_H: int = 0
    GAP: int = 0

    def __init__(self) -> None:
        super().__init__()
        self._cards: Sequence[QWidget] = []
        self._layout = QGridLayout(self)
        self._layout.setSpacing(self.GAP)
        self._layout.setContentsMargins(self.GAP, self.GAP, self.GAP, self.GAP)
        self._last_cols = 0

    def set_cards(self, cards: Sequence[QWidget]) -> None:
        self.__clear_layout()
        self._cards = cards
        self.__reflow(self.width() or 900)

    def resizeEvent(self, event: QResizeEvent) -> None:
        self.__reflow(event.size().width())
        super().resizeEvent(event)

    def __clear_layout(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if cast(QLayoutItem, item).widget():
                cast(QWidget, cast(QLayoutItem, item).widget()).setParent(None)

    def __reflow(self, available_w: int) -> None:
        cols = max(1, available_w // (self.CARD_W + self.GAP))
        if cols == self._last_cols and self._layout.count() == len(self._cards):
            return
        self._last_cols = cols
        self.__clear_layout()
        n = len(self._cards)

        for c in range(cols + 2):
            self._layout.setColumnStretch(c, 0)

        if n == 1:
            self._layout.addWidget(
                self._cards[0],
                0,
                0,
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
            )
            self._layout.setColumnStretch(1, 1)
        else:
            for i, card in enumerate(self._cards):
                self._layout.addWidget(
                    card,
                    i // cols,
                    i % cols,
                    Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter,
                )

        rows = (n + cols - 1) // cols if self._cards else 0
        self.setMinimumHeight(rows * (self.CARD_H + self.GAP) + self.GAP)


STATS_PANEL_SCREEN_FRACTION = 0.25


def stats_panel_width(widget: QWidget, margin: int = 16) -> int:
    """Ширина панели показателей: не больше 25 % экрана, чтобы не закрывать видео."""
    screen = widget.screen()
    screen_w = screen.geometry().width() if screen is not None else widget.width()
    cap = int(screen_w * STATS_PANEL_SCREEN_FRACTION)
    available = max(0, widget.width() - 2 * margin)
    return max(1, min(cap, available)) if available else max(1, cap)


def stats_label_qss() -> str:
    return f"""
        QLabel {{
            background: transparent;
            color: {theme.TEXT_PRIMARY};
            border: none;
            font-family: monospace;
            font-size: {theme.FONT_SIZE_SM - 1}px;
            padding: 10px 14px;
        }}
    """


def build_stats_scroll(label: QLabel, parent: QWidget) -> QScrollArea:
    """Панель показателей не влезает по высоте — кладём метку в прокрутку."""
    scroll = QScrollArea(parent)
    scroll.setWidget(label)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    scroll.setStyleSheet(f"""
        QScrollArea {{
            background: rgba(0,0,0,0.72);
            border: 1px solid rgba(255,255,255,0.12);
            border-radius: {theme.RADIUS_MD}px;
        }}
        QScrollArea > QWidget > QWidget {{ background: transparent; }}
        QScrollBar:vertical {{
            background: transparent;
            width: 8px;
            margin: 4px 2px 4px 0;
        }}
        QScrollBar::handle:vertical {{
            background: rgba(255,255,255,0.28);
            border-radius: 4px;
            min-height: 24px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: transparent;
        }}
    """)
    return scroll


def fit_stats_scroll(
    scroll: QScrollArea, label: QLabel, x: int, y: int, width: int, max_height: int
) -> None:
    """Панель тянется по содержимому и упирается в max_height — дальше прокрутка."""
    viewport_w = max(1, width - 2 * scroll.frameWidth() - 2)
    needed = label.heightForWidth(viewport_w)
    if needed <= 0:
        needed = label.sizeHint().height()
    height = max(0, min(max_height, needed + 2 * scroll.frameWidth() + 2))
    scroll.setGeometry(x, y, width, height)
