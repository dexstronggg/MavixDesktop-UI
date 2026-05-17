"""Shared UI utilities for screens package."""
from PySide6.QtCore import Qt, QSize, QEvent, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtGui import QPixmap, QPainter, QColor, QIcon, QFont, QLinearGradient
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget, QPushButton, QGridLayout

from pathlib import Path

from mavixdesktop.ui.style import theme

_ICONS_DIR = Path(__file__).parent.parent / 'icons'


# ── SVG helpers ───────────────────────────────────────────────────────────────

def svg_pixmap(name: str, size: int, color: str | None = None) -> QPixmap:
    """Загрузить SVG из ui/icons/<name> и вернуть QPixmap.

    Если передан ``color`` (hex или CSS-имя), результат перекрашивается:
    сохраняется альфа-маска отрисованных фигур, цвет RGB заменяется на
    указанный. Это обходит ограничение QSvgRenderer, у которого нет
    `currentColor` из CSS — без перекраски иконки рендерятся чёрным
    stroke-ом и не видны на тёмном фоне.
    """
    renderer = QSvgRenderer(str(_ICONS_DIR / name))
    px = QPixmap(QSize(size, size))
    px.fill(Qt.transparent)
    p = QPainter(px)
    renderer.render(p)
    p.end()
    if color is None:
        return px
    # Перекраска через composition: сначала заливаем сплошным цветом,
    # потом DestinationIn оставляет только пиксели, где у исходного
    # SVG была непрозрачность.
    tinted = QPixmap(QSize(size, size))
    tinted.fill(QColor(color))
    p = QPainter(tinted)
    p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    p.drawPixmap(0, 0, px)
    p.end()
    return tinted


def mavix_logo_pixmap(size: int) -> QPixmap:
    """Логотип Mavix — cyan-градиентный квадрат со скруглёнными углами и
    точно центрированной белой буквой ``M``. Рисуется QPainter-ом, без
    QSvgRenderer — так Qt не теряет ни центрирование, ни шрифт.
    """
    px = QPixmap(QSize(size, size))
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)

    # Background: cyan linear gradient
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0.0, QColor('#22d3ee'))
    grad.setColorAt(1.0, QColor('#06b6d4'))
    p.setBrush(grad)
    p.setPen(Qt.NoPen)
    radius = size * 0.26
    p.drawRoundedRect(0, 0, size, size, radius, radius)

    # Centered M
    font = QFont('Inter')
    font.setPixelSize(int(size * 0.62))
    font.setWeight(QFont.Weight.Bold)
    p.setFont(font)
    p.setPen(QColor('#001017'))
    p.drawText(0, 0, size, size, Qt.AlignCenter, 'M')
    p.end()
    return px


# ── Overlay button factories ───────────────────────────────────────────────────

def overlay_btn(text: str, parent: QWidget, size: int = None) -> QPushButton:
    """Semi-transparent round button with a text symbol (arrows, etc.)."""
    if size is None:
        size = theme.OVERLAY_BTN_SIDE
    btn = QPushButton(text, parent)
    btn.setFixedSize(size, size)
    btn.setStyleSheet(f"""
        QPushButton {{
            background: rgba(0,0,0,0.55);
            color: {theme.TEXT_PRIMARY};
            border: 1px solid rgba(255,255,255,0.15);
            border-radius: {size // 2}px;
            font-size: {theme.OVERLAY_BTN_SIDE_FONT}px;
        }}
        QPushButton:hover {{
            background: rgba(42,130,218,0.65);
            border-color: {theme.ACCENT};
        }}
        QPushButton:pressed {{
            background: rgba(31,106,176,0.85);
        }}
        QPushButton:disabled {{
            color: rgba(255,255,255,0.20);
            background: rgba(0,0,0,0.30);
            border-color: rgba(255,255,255,0.05);
        }}
    """)
    return btn


def overlay_icon_btn(svg_name: str, parent: QWidget,
                     size: int = None, icon_size: int = None) -> QPushButton:
    """Semi-transparent round button with an SVG icon."""
    if size is None:
        size = theme.OVERLAY_BTN_CORNER
    if icon_size is None:
        icon_size = theme.OVERLAY_BTN_CORNER_ICON
    btn = QPushButton(parent)
    btn.setFixedSize(size, size)
    btn.setIcon(QIcon(svg_pixmap(svg_name, icon_size, color=theme.TEXT_PRIMARY)))
    btn.setIconSize(QSize(icon_size, icon_size))
    btn.setStyleSheet(f"""
        QPushButton {{
            background: rgba(0,0,0,0.55);
            border: 1px solid rgba(255,255,255,0.15);
            border-radius: {size // 2}px;
        }}
        QPushButton:hover {{
            background: rgba(42,130,218,0.65);
            border-color: {theme.ACCENT};
        }}
        QPushButton:pressed {{
            background: rgba(31,106,176,0.85);
        }}
        QPushButton:disabled {{
            background: rgba(0,0,0,0.30);
            border-color: rgba(255,255,255,0.05);
        }}
    """)
    return btn


# ── AnimatedCard ───────────────────────────────────────────────────────────────

class AnimatedCard(QWidget):
    """Base for cards with a hover-animated accent bar at the bottom.

    Subclasses can override:
        _ANIM_DURATION  — ms
        _BAR_RADIUS     — px
        _BAR_HEIGHT     — px
        _on_hover(bool) — called on HoverEnter/Leave; default animates bar only
    """
    _ANIM_DURATION = 500
    _BAR_RADIUS    = theme.RADIUS_LG
    _BAR_HEIGHT    = 3

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._bar_progress = 0
        self._bar_anim = QPropertyAnimation(self, b'bar_progress')
        self._bar_anim.setDuration(self._ANIM_DURATION)
        self._bar_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.setAttribute(Qt.WA_Hover, True)

    @Property(int)
    def bar_progress(self):
        return self._bar_progress

    @bar_progress.setter
    def bar_progress(self, value: int):
        self._bar_progress = value
        self.update()

    def event(self, e):
        if e.type() == QEvent.HoverEnter:
            self._on_hover(True)
        elif e.type() == QEvent.HoverLeave:
            self._on_hover(False)
        return super().event(e)

    def _on_hover(self, hovered: bool):
        self._animate_bar(1000 if hovered else 0)

    def _animate_bar(self, target: int):
        self._bar_anim.stop()
        self._bar_anim.setStartValue(self._bar_progress)
        self._bar_anim.setEndValue(target)
        self._bar_anim.start()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._bar_progress <= 0:
            return
        r = self._BAR_RADIUS
        bar_max_w = self.width() - 2 * r
        bar_w = max(0, int(self._bar_progress * bar_max_w / 1000))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.ACCENT))
        painter.drawRoundedRect(r, self.height() - self._BAR_HEIGHT, bar_w, self._BAR_HEIGHT, 1, 1)
        painter.end()


# ── CardGrid ───────────────────────────────────────────────────────────────────

class CardGrid(QWidget):
    """Responsive grid that reflows columns on resize.

    Subclasses must set CARD_W, CARD_H, GAP as class attributes.
    """
    CARD_W: int = 0
    CARD_H: int = 0
    GAP:    int = 0

    def __init__(self):
        super().__init__()
        self._cards: list = []
        self._layout = QGridLayout(self)
        self._layout.setSpacing(self.GAP)
        self._layout.setContentsMargins(self.GAP, self.GAP, self.GAP, self.GAP)
        self._last_cols = 0

    def set_cards(self, cards: list):
        self.__clear_layout()
        self._cards = cards
        self.__reflow(self.width() or 900)

    def resizeEvent(self, event):
        self.__reflow(event.size().width())
        super().resizeEvent(event)

    def __clear_layout(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

    def __reflow(self, available_w: int):
        cols = max(1, available_w // (self.CARD_W + self.GAP))
        if cols == self._last_cols and self._layout.count() == len(self._cards):
            return
        self._last_cols = cols
        self.__clear_layout()
        for i, card in enumerate(self._cards):
            self._layout.addWidget(card, i // cols, i % cols, Qt.AlignTop | Qt.AlignLeft)
        rows = (len(self._cards) + cols - 1) // cols if self._cards else 0
        self.setMinimumHeight(rows * (self.CARD_H + self.GAP) + self.GAP)
