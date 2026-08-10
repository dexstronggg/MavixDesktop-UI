from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QPushButton, QWidget

from mavixdesktop.ui.style import theme


class CloseButton(QPushButton):
    """Кнопка «закрыть» с крестиком, нарисованным через QPainter.

    Текстовые глифы крестика (✕, ×) не гарантированы во всех шрифтах на всех
    ОС — на некоторых системах символ превращается в пустой прямоугольник.
    Поэтому крестик рисуется программно: белые линии, одинаково выглядят
    на Linux, Windows и macOS независимо от установленных шрифтов.
    """

    def __init__(self, parent: QWidget | None = None, size: int = 32) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hovered = False

    def enterEvent(self, event: object) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)  # type: ignore[arg-type]

    def leaveEvent(self, event: object) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)  # type: ignore[arg-type]

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        bg_alpha = 36 if self._hovered else 15
        p.fillRect(0, 0, w, h, QColor(255, 255, 255, bg_alpha))

        pen = QPen(QColor(theme.BORDER))
        pen.setWidth(1)
        p.setPen(pen)
        p.drawRoundedRect(1, 1, w - 2, h - 2, theme.RADIUS_SM, theme.RADIUS_SM)

        pen = QPen(QColor('#FFFFFF'))
        pen.setWidth(2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        m = max(5, w // 5)
        cx, cy = w // 2, h // 2
        p.drawLine(cx - m, cy - m, cx + m, cy + m)
        p.drawLine(cx - m, cy + m, cx + m, cy - m)


class StickWidget(QWidget):
    def __init__(
        self,
        label: str = '',
        parent: QWidget | None = None,
        bg_alpha: int = 255,
        label_font_px: int = 9,
    ) -> None:
        super().__init__(parent)
        self.setFixedSize(120, 120)
        self._x = 0.0
        self._y = 0.0
        self._label = label
        self._bg_alpha = bg_alpha
        self._label_font_px = label_font_px

    def set_position(self, x: float, y: float) -> None:
        self._x = max(-1.0, min(1.0, x))
        self._y = max(-1.0, min(1.0, y))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        bg = QColor(theme.BG_INPUT)
        bg.setAlpha(self._bg_alpha)
        p.fillRect(0, 0, w, h, bg)

        pen = QPen(QColor(theme.TEXT_DISABLED))
        pen.setWidth(1)
        p.setPen(pen)
        p.drawRect(0, 0, w - 1, h - 1)

        p.setPen(QPen(QColor(theme.BORDER_DARK)))
        p.drawLine(w // 2, 0, w // 2, h)
        p.drawLine(0, h // 2, w, h // 2)

        cx = int((self._x + 1) / 2 * (w - 12)) + 6
        cy = int((1 - (self._y + 1) / 2) * (h - 12)) + 6
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.CYAN))
        p.drawEllipse(cx - 6, cy - 6, 12, 12)

        if self._label:
            font = p.font()
            font.setPixelSize(self._label_font_px)
            p.setFont(font)
            p.setPen(QColor(theme.TEXT_MUTED))
            p.drawText(4, h - 4, self._label)
        p.end()
