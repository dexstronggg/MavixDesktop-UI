from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from mavixdesktop.ui.style import theme


class StickWidget(QWidget):
    def __init__(self, label: str = '', parent=None, bg_alpha: int = 255, label_font_px: int = 9):
        super().__init__(parent)
        self.setFixedSize(120, 120)
        self._x = 0.0
        self._y = 0.0
        self._label = label
        self._bg_alpha = bg_alpha
        self._label_font_px = label_font_px

    def set_position(self, x: float, y: float):
        self._x = max(-1.0, min(1.0, x))
        self._y = max(-1.0, min(1.0, y))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
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
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.CYAN))
        p.drawEllipse(cx - 6, cy - 6, 12, 12)

        if self._label:
            font = p.font()
            font.setPixelSize(self._label_font_px)
            p.setFont(font)
            p.setPen(QColor(theme.TEXT_MUTED))
            p.drawText(4, h - 4, self._label)
        p.end()
