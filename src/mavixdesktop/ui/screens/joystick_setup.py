"""Joystick setup screen: list, calibration, and stick preview."""

from __future__ import annotations

import json
import platform
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pygame
from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QGuiApplication,
    QHideEvent,
    QIcon,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mavixdesktop.core.config import settings
from mavixdesktop.joystick import calibration as joystick_calibration
from mavixdesktop.joystick.input import JoystickInput
from mavixdesktop.joystick.manager import build_sdl_config, list_joysticks
from mavixdesktop.ui.screens.utils import AnimatedCard, CardGrid, svg_pixmap
from mavixdesktop.ui.screens.widgets import StickWidget
from mavixdesktop.ui.style import theme


class JoystickManager:
    @staticmethod
    def list_joysticks() -> list[str]:
        return list_joysticks()


class JoystickCalibration:
    @staticmethod
    def save(cal: dict[str, Any], joystick_name: str) -> Path:
        return joystick_calibration.save(
            cal, joystick_name, data_dir=settings.data_path
        )

    @staticmethod
    def load(joystick_name: str) -> dict[str, Any] | None:
        return joystick_calibration.load(joystick_name, data_dir=settings.data_path)

    @staticmethod
    def validate(data: dict[str, Any]) -> tuple[bool, str]:
        return joystick_calibration.validate(data)


_build_sdl_config = build_sdl_config

_STEP_CENTER = 0
_STEP_THR_MAX = 1
_STEP_THR_MIN = 2
_STEP_YAW_MAX = 3
_STEP_YAW_MIN = 4
_STEP_PITCH_MAX = 5
_STEP_PITCH_MIN = 6
_STEP_ROLL_MAX = 7
_STEP_ROLL_MIN = 8
_STEP_ARM = 9
_STEP_RELEASE = 10
_STEP_DONE = 11

_STEPS = [
    'Шаг 1/11: установите все стики в ЦЕНТР — Далее',
    'Шаг 2/11: ГАЗ — потяните вверх (МАКСИМУМ) — Далее',
    'Шаг 3/11: ГАЗ — потяните вниз (МИНИМУМ) — Далее',
    'Шаг 4/11: РЫСКАНИЕ — поверните вправо (МАКСИМУМ) — Далее',
    'Шаг 5/11: РЫСКАНИЕ — поверните влево (МИНИМУМ) — Далее',
    'Шаг 6/11: ТАНГАЖ — наклоните вперёд (МАКСИМУМ) — Далее',
    'Шаг 7/11: ТАНГАЖ — наклоните назад (МИНИМУМ) — Далее',
    'Шаг 8/11: КРЕН — наклоните вправо (МАКСИМУМ) — Далее',
    'Шаг 9/11: КРЕН — наклоните влево (МИНИМУМ) — Далее',
    'Шаг 10/11: нажмите кнопку ARM/DISARM на пульте',
    'Шаг 11/11: нажмите кнопку СБРОСА ГРУЗА.\n\n'
    'Если сброса нет — нажмите «Пропустить».',
    'Калибровка завершена!\n\nНажмите «Готово» для сохранения.',
]


class _StepProgress(QWidget):
    _TOTAL = 11
    _DOT_SIZE = 8
    _DOT_GAP = 12
    _HALO_PAD = 4

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current = 0
        self.setFixedHeight(self._DOT_SIZE + 2 * self._HALO_PAD + 2)

    def set_current(self, step: int) -> None:
        if step == self._current:
            return
        self._current = step
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        accent = QColor(theme.ACCENT)
        halo = QColor(accent)
        halo.setAlpha(72)
        future = QColor(theme.TEXT_MUTED)
        d = self._DOT_SIZE
        gap = self._DOT_GAP
        pad = self._HALO_PAD
        total_w = self._TOTAL * d + (self._TOTAL - 1) * gap
        x = (self.width() - total_w) // 2
        y = (self.height() - d) // 2
        done = self._current >= self._TOTAL
        for i in range(self._TOTAL):
            if done or i < self._current:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(accent)
                p.drawEllipse(x, y, d, d)
            elif i == self._current:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(halo)
                p.drawEllipse(x - pad, y - pad, d + 2 * pad, d + 2 * pad)
                p.setBrush(accent)
                p.drawEllipse(x, y, d, d)
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(future)
                p.drawEllipse(x, y, d, d)
            x += d + gap
        p.end()


_CARD_W = 220
_CARD_H = 200
_ICON_SZ = 56
_GAP = 20


class _PopupRow(AnimatedCard):
    _ANIM_DURATION = 200
    _BAR_RADIUS = theme.RADIUS_SM
    _BAR_HEIGHT = 2

    def __init__(
        self, text: str, callback: Callable[[], None], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setFixedHeight(42)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._callback = callback

        self.setStyleSheet('background: transparent; border: none;')
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 0, 24, 0)
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; font-size: {theme.FONT_SIZE_SM}px;'
            'background: transparent; border: none;'
        )
        lay.addWidget(lbl)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._callback()
        super().mousePressEvent(event)


class _CardMenu(QFrame):
    def __init__(
        self, items: list[tuple[str, Callable[[], None]]], parent: QWidget | None = None
    ) -> None:
        super().__init__(
            parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            QFrame {{
                background: {theme.BG_SURFACE};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS_MD}px;
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 6)
        lay.setSpacing(2)
        for text, callback in items:
            row = _PopupRow(
                text, cast(Callable[[], None], lambda cb=callback: (cb(), self.close()))
            )
            row.setMinimumWidth(230)
            lay.addWidget(row)
        self.adjustSize()

    def show_at(self, pos: QPoint) -> None:
        self.move(pos)
        self.show()


class JoystickCard(AnimatedCard):
    clicked = Signal(int)
    action = Signal(int, str)

    def __init__(self, index: int, name: str, calibrated: bool) -> None:
        super().__init__()
        self._index = index
        self._active_menu = None

        self.setFixedSize(_CARD_W, _CARD_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._style_normal = f"""
            QWidget#jsCard {{
                background: {theme.BG_INPUT};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS_LG}px;
            }}
        """
        self._style_hover = f"""
            QWidget#jsCard {{
                background: {theme.BG_HOVER};
                border: 1px solid {theme.ACCENT};
                border-radius: {theme.RADIUS_LG}px;
            }}
        """
        self.setObjectName('jsCard')
        self.setStyleSheet(self._style_normal)

        lay = QVBoxLayout(self)
        lay.setSpacing(6)
        lay.setContentsMargins(14, 14, 14, 6)

        icon_lbl = QLabel()
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setPixmap(svg_pixmap('joystick.svg', _ICON_SZ, color=theme.ACCENT))
        icon_lbl.setStyleSheet('background: transparent; border: none;')
        icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        name_lbl = QLabel(name)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setWordWrap(True)
        name_lbl.setFixedHeight(34)
        name_lbl.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; font-size: {theme.FONT_SIZE_SM}px;'
            'font-weight: 600; background: transparent; border: none;'
        )

        status_row = QWidget()
        status_row.setStyleSheet('background: transparent; border: none;')
        sr = QHBoxLayout(status_row)
        sr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sr.setSpacing(6)
        sr.setContentsMargins(0, 0, 0, 0)

        dot = QLabel('●')
        dot.setStyleSheet(
            f'color: {theme.STATUS_READY if calibrated else theme.STATUS_ERROR}; font-size: 11px;'
            'background: transparent; border: none;'
        )
        status_lbl = QLabel('откалиброван' if calibrated else 'не откалиброван')
        status_lbl.setStyleSheet(
            f'color: {theme.TEXT_MUTED}; font-size: 12px;'
            'background: transparent; border: none;'
        )
        sr.addWidget(dot)
        sr.addWidget(status_lbl)

        lay.addWidget(icon_lbl)
        lay.addWidget(name_lbl)
        lay.addWidget(status_row)

        actions_row = QWidget()
        actions_row.setStyleSheet('background: transparent; border: none;')
        ar = QHBoxLayout(actions_row)
        ar.setContentsMargins(0, 0, 0, 0)
        ar.setSpacing(6)

        self._action_buttons: list[QToolButton] = []
        for ic, label, sub in [
            ('tune.svg', 'Калибровка', 'calibrate'),
            ('upload.svg', 'Загрузить', 'file'),
            ('save.svg', 'Сохранить', 'file_save'),
        ]:
            b = QToolButton()
            b.setIcon(QIcon(svg_pixmap(ic, 18, color=theme.TEXT_PRIMARY)))
            b.setIconSize(QSize(18, 18))
            b.setText(label)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setFixedHeight(52)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setAutoRaise(True)
            b.setStyleSheet(f"""
                QToolButton {{
                    background: transparent;
                    border: none;
                    border-radius: {theme.RADIUS_MD}px;
                    color: {theme.TEXT_MUTED};
                    font-size: {theme.FONT_SIZE_SM - 3}px;
                    padding: 4px 0;
                }}
                QToolButton:hover {{
                    background: {theme.ACCENT_SUBTLE};
                    color: {theme.ACCENT};
                }}
                QToolButton:pressed {{
                    background: {theme.BG_INPUT};
                    color: {theme.ACCENT};
                }}
            """)
            b.clicked.connect(
                lambda _checked=False, s=sub: self.action.emit(self._index, s)
            )
            ar.addWidget(b, 1)
            self._action_buttons.append(b)

        lay.addWidget(actions_row)

    def _on_hover(self, hovered: bool) -> None:
        self.setStyleSheet(self._style_hover if hovered else self._style_normal)
        self._animate_bar(1000 if hovered else 0)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._index)
        super().mousePressEvent(event)


class _JoystickGrid(CardGrid):
    CARD_W = _CARD_W
    CARD_H = _CARD_H
    GAP = _GAP


class _StickPreviewDialog(QDialog):
    def __init__(
        self,
        joystick_index: int,
        joystick_name: str,
        calibration: dict[str, Any],
        parent: QWidget | None = None,
        on_takeoff: Callable[[int, dict[str, Any]], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_takeoff = on_takeoff
        self._joystick_index = joystick_index
        self._calibration = calibration
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setFixedSize(340, 270 if on_takeoff else 180)
        self.setStyleSheet(f"""
            QDialog {{
                background: {theme.BG_SURFACE};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS_LG}px;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 10, 16, 16)
        root.setSpacing(10)

        self.__build_title_bar(joystick_name, root)
        self.__build_sticks(root)

        if on_takeoff:
            takeoff_btn = QPushButton('Взлёт')
            takeoff_btn.setFixedHeight(40)
            takeoff_btn.setStyleSheet(theme.QSS_BUTTON_PRIMARY)
            takeoff_btn.clicked.connect(self.__takeoff)
            root.addWidget(takeoff_btn)

        self._js = JoystickInput(joystick_index, calibration)
        self._timer = QTimer(interval=30)
        self._timer.timeout.connect(self.__poll)
        self._timer.start()

    def __build_title_bar(self, joystick_name: str, root: QVBoxLayout) -> None:
        title_row = QHBoxLayout()
        title_lbl = QLabel(joystick_name)
        title_lbl.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; font-size: {theme.FONT_SIZE_SM}px;'
            'font-weight: 600; background: transparent;'
        )
        title_lbl.setWordWrap(False)
        close_btn = QPushButton()
        close_btn.setFixedSize(28, 28)
        close_btn.setIcon(QIcon(svg_pixmap('cross.svg', 14, color=theme.TEXT_PRIMARY)))
        close_btn.setIconSize(QSize(14, 14))
        close_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 14px;
            }
            QPushButton:hover {
                background: rgba(255,80,80,0.20);
            }
        """)
        close_btn.clicked.connect(self.close)
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        title_row.addWidget(close_btn)
        root.addLayout(title_row)

    def __build_sticks(self, root: QVBoxLayout) -> None:
        sticks_row = QHBoxLayout()
        sticks_row.addStretch()
        self._stick_l = StickWidget('Тяга / Рыск.', label_font_px=12)
        self._stick_r = StickWidget('Тангаж / Крен', label_font_px=12)
        sticks_row.addWidget(self._stick_l)
        sticks_row.addSpacing(20)
        sticks_row.addWidget(self._stick_r)
        sticks_row.addStretch()
        root.addLayout(sticks_row)

    def __poll(self) -> None:
        try:
            thr, yaw, pitch, roll = self._js.get_stick_positions()
            self._stick_l.set_position(yaw, thr)
            self._stick_r.set_position(roll, pitch)
        except Exception:
            pass

    def __takeoff(self) -> None:
        self._timer.stop()
        self.accept()
        if self._on_takeoff:
            self._on_takeoff(self._joystick_index, self._calibration)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._timer.stop()
        super().closeEvent(event)


class _CenteredPanel(QWidget):
    """Плашка по центру окна.

    Дочерний виджет, а не окно: Wayland запрещает приложению самому
    расставлять окна, там `move()` для окна просто игнорируется.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName('centeredPanel')
        self.setFixedSize(360, 80)
        self.setStyleSheet(f"""
            QWidget#centeredPanel {{
                background: {theme.BG_SURFACE};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS_LG}px;
            }}
        """)
        self.hide()

    def show_centered(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            screen = QGuiApplication.primaryScreen().geometry()
            self.move(
                screen.x() + (screen.width() - self.width()) // 2,
                screen.y() + (screen.height() - self.height()) // 2,
            )
        else:
            parent.installEventFilter(self)
            self.__recenter()
        self.show()
        self.raise_()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize and watched is self.parentWidget():
            self.__recenter()
        return super().eventFilter(watched, event)

    def __recenter(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        area = parent.rect()
        self.move(
            area.x() + (area.width() - self.width()) // 2,
            area.y() + (area.height() - self.height()) // 2,
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        parent = self.parentWidget()
        if parent is not None:
            parent.removeEventFilter(self)
        super().closeEvent(event)


_REOPEN_NOTE = (
    'Если QGroundControl уже было открыто раньше — закройте его: '
    'приложение откроет своё окно с нужными настройками'
)


class QGCSearchOverlay(_CenteredPanel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(360, 124)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        self._label = QLabel('Ищу QGroundControl')
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; font-size: {theme.FONT_SIZE_BASE}px;'
            'font-weight: 600; background: transparent;'
        )
        lay.addWidget(self._label)

        note = QLabel(_REOPEN_NOTE)
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setWordWrap(True)
        note.setStyleSheet(
            f'color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE_SM}px;'
            'background: transparent;'
        )
        lay.addWidget(note)

        self._dots = 0
        self._timer = QTimer(interval=350)
        self._timer.timeout.connect(self.__tick)
        self._timer.start()

    def __tick(self) -> None:
        self._dots = (self._dots + 1) % 4
        self._label.setText('Ищу QGroundControl' + '.' * self._dots)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._timer.stop()
        super().closeEvent(event)


class QGCLaunchingOverlay(_CenteredPanel):
    def __init__(
        self, qgc_proc: subprocess.Popen[bytes], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setFixedSize(360, 124)

        self._qgc_proc = qgc_proc
        self._deadline = time.monotonic() + 6.0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lbl = QLabel('Открываю QGroundControl…')
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; font-size: {theme.FONT_SIZE_BASE}px;'
            'font-weight: 600; background: transparent;'
        )
        lay.addWidget(lbl)

        note = QLabel(_REOPEN_NOTE)
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setWordWrap(True)
        note.setStyleSheet(
            f'color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE_SM}px;'
            'background: transparent;'
        )
        lay.addWidget(note)

        self._timer = QTimer(interval=500)
        self._timer.timeout.connect(self.__check)
        self._timer.start()

    def __check(self) -> None:
        if self._qgc_proc.poll() is not None:
            self.close()
            return
        if self.__qgc_window_visible() or time.monotonic() > self._deadline:
            self.close()

    def __qgc_window_visible(self) -> bool:
        if platform.system() != 'Linux':
            return False
        try:
            result = subprocess.run(
                ['wmctrl', '-lp'],
                capture_output=True,
                text=True,
                timeout=0.5,
            )
            if result.returncode != 0:
                return False
            if 'qgroundcontrol' in result.stdout.lower():
                return True
            pids = self.__qgc_pid_tree()
            for line in result.stdout.splitlines():
                parts = line.split(None, 4)
                if len(parts) >= 3 and parts[2] in pids:
                    return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return False

    def __qgc_pid_tree(self) -> set[str]:
        if platform.system() != 'Linux':
            return {str(self._qgc_proc.pid)}
        pids = {str(self._qgc_proc.pid)}
        try:
            result = subprocess.run(
                ['pgrep', '-P', str(self._qgc_proc.pid)],
                capture_output=True,
                text=True,
                timeout=0.5,
            )
            if result.returncode == 0:
                pids.update(result.stdout.split())
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return pids

    def closeEvent(self, event: QCloseEvent) -> None:
        self._timer.stop()
        super().closeEvent(event)


class JoystickSetupPage(QWidget):
    DEMO_JOYSTICK_NAME = 'Демо-контроллер (Mock)'

    def __init__(
        self,
        on_back: Callable[[], None],
        on_takeoff: Callable[[int, dict[str, Any]], None] | None = None,
        demo: bool = False,
    ) -> None:
        super().__init__()
        self._joystick_names: list[str] | None = None
        self._joystick_cal_states: list[bool] = []
        self._on_takeoff = on_takeoff
        self._fc_type: str = 'none'
        self._demo = demo

        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        root.addWidget(self.__build_top_bar(on_back))

        self._grid = _JoystickGrid()
        scroll = QScrollArea()
        scroll.setWidget(self._grid)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._empty = QLabel(
            'Контроллеры не найдены\n\nПодключите джойстик по USB —\nсписок обновится автоматически'
        )
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet(
            f'color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE_BASE}px;'
        )
        self._empty.hide()

        root.addWidget(scroll, 1)
        root.addWidget(self._empty, 1)

        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.setInterval(3000)
        self._auto_refresh_timer.timeout.connect(self._refresh)

        self._refresh()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._auto_refresh_timer.start()

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        self._auto_refresh_timer.stop()

    def __build_top_bar(self, on_back: Callable[[], None]) -> QWidget:
        from mavixdesktop.ui.screens.drone_list_page import _brand_widget, _icon_button

        top_bar = QWidget()
        top_bar.setObjectName('topBar')
        top_bar.setStyleSheet(f"""
            QWidget#topBar {{
                background: {theme.BG_SURFACE};
                border-bottom: 1px solid {theme.BORDER};
            }}
        """)
        top_bar.setFixedHeight(64)
        tb = QHBoxLayout(top_bar)
        tb.setContentsMargins(28, 0, 28, 0)
        tb.setSpacing(12)

        tb.addWidget(_brand_widget(top_bar))
        sep = QFrame()
        sep.setFixedSize(1, 22)
        sep.setStyleSheet(f'background: {theme.BORDER}; border: none;')
        tb.addSpacing(8)
        tb.addWidget(sep)
        tb.addSpacing(8)

        title = QLabel('Джойстики')
        title.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; font-size: {theme.FONT_SIZE_LG}px;'
            f'font-weight: 600; background: transparent; border: none;'
            f'font-family: {theme.FONT_FAMILY};'
        )
        tb.addWidget(title)
        tb.addStretch()

        back_btn = _icon_button('arrow_back.svg', 'Назад', top_bar)
        back_btn.setToolTip('Назад к экрану дрона')
        back_btn.clicked.connect(on_back)
        tb.addWidget(back_btn)

        return top_bar

    def set_fc_type(self, fc_type: str) -> None:
        self._fc_type = fc_type

    def _refresh(self, force: bool = False) -> None:
        names = JoystickManager.list_joysticks()
        if self._demo and not names:
            names = [self.DEMO_JOYSTICK_NAME]

        cal_states = [bool(JoystickCalibration.load(name)) for name in names]
        if (
            not force
            and names == self._joystick_names
            and cal_states == self._joystick_cal_states
        ):
            return
        self._joystick_names = names
        self._joystick_cal_states = cal_states

        if not self._joystick_names:
            self._empty.show()
            self._grid.hide()
            self._grid.set_cards([])
            return

        self._empty.hide()
        self._grid.show()

        cards = []
        for i, name in enumerate(self._joystick_names):
            card = JoystickCard(i, name, calibrated=cal_states[i])
            card.clicked.connect(self._on_card_clicked)
            card.action.connect(self._on_card_action)
            cards.append(card)
        self._grid.set_cards(cards)

    def _on_card_clicked(self, index: int) -> None:
        name = cast(list[str], self._joystick_names)[index]
        takeoff_cb = self._on_takeoff if self._fc_type in ('crsf', 'mavlink') else None
        saved = JoystickCalibration.load(name)
        if saved:
            dlg = _StickPreviewDialog(
                index, name, saved, parent=self, on_takeoff=takeoff_cb
            )
            dlg.exec()
        else:
            cal_dlg = JoystickCalibrationDialog(index, name, parent=self)
            if cal_dlg.exec() == QDialog.DialogCode.Accepted and cal_dlg.calibration:
                self._refresh(force=True)
                dlg = _StickPreviewDialog(
                    index, name, cal_dlg.calibration, parent=self, on_takeoff=takeoff_cb
                )
                dlg.exec()

    def _on_card_action(self, index: int, action: str) -> None:
        name = cast(list[str], self._joystick_names)[index]
        if action == 'file':
            self._load_from_file(index, name)
        elif action == 'calibrate':
            dlg = JoystickCalibrationDialog(index, name, parent=self)
            if dlg.exec() == QDialog.DialogCode.Accepted and dlg.calibration:
                self._refresh(force=True)
        elif action == 'file_save':
            self._save_to_file(index, name)

    def _load_from_file(self, index: int, name: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, 'Загрузить калибровку', '', 'JSON (*.json)'
        )
        if not path:
            return
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except Exception as exc:
            QMessageBox.critical(self, 'Ошибка чтения файла', str(exc))
            return
        ok, msg = JoystickCalibration.validate(data)
        if not ok:
            QMessageBox.critical(self, 'Неверный формат калибровки', msg)
            return
        JoystickCalibration.save(data, name)
        self._refresh(force=True)
        QMessageBox.information(
            self,
            'Калибровка загружена',
            f'Калибровка для «{name}» успешно загружена и сохранена.',
        )

    def _save_to_file(self, index: int, name: str) -> None:
        cal = JoystickCalibration.load(name)
        if not cal:
            QMessageBox.warning(
                self, 'Нет калибровки', f'Джойстик «{name}» не откалиброван.'
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self, 'Сохранить калибровку', f'{name}.json', 'JSON (*.json)'
        )
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(cal, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            QMessageBox.critical(self, 'Ошибка сохранения', str(exc))
            return
        QMessageBox.information(self, 'Сохранено', f'Калибровка сохранена в:\n{path}')


class JoystickCalibrationDialog(QDialog):
    def __init__(
        self, joystick_index: int, joystick_name: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle('Калибровка джойстика')
        self.setMinimumWidth(460)
        self._step = 0
        self._data: dict[str, Any] = {}
        self._joystick_name = joystick_name
        self.calibration: dict[str, Any] | None = None
        self._arm_btn_states: list[bool] | None = None
        self._arm_axis_states: list[bool] | None = None

        pygame.joystick.init()
        self._js = pygame.joystick.Joystick(joystick_index)
        self._js.init()

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        sticks_row = QHBoxLayout()
        sticks_row.addStretch()
        self._stick_l = StickWidget('Рыск/Тяга', label_font_px=18)
        self._stick_r = StickWidget('Крен/Тангаж', label_font_px=18)
        sticks_row.addWidget(self._stick_l)
        sticks_row.addSpacing(16)
        sticks_row.addWidget(self._stick_r)
        sticks_row.addStretch()
        layout.addLayout(sticks_row)

        self._progress = _StepProgress()
        layout.addWidget(self._progress)

        self._instruction = QLabel()
        self._instruction.setWordWrap(True)
        self._instruction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._instruction.setStyleSheet('font-size: 13px; padding: 8px;')
        layout.addWidget(self._instruction)

        self._next_btn = QPushButton('Далее')
        self._next_btn.clicked.connect(self._on_next)
        layout.addWidget(self._next_btn)

        self._poll_timer = QTimer(interval=30)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()

        self._update_ui()

    def _read_axes(self) -> list[float]:
        pygame.event.pump()
        return [self._js.get_axis(i) for i in range(self._js.get_numaxes())]

    def _detect_axis(self, vals: list[float], exclude: set[int | None]) -> int:
        center = self._data.get('center', [0.0] * len(vals))
        deltas = [
            (abs(vals[i] - center[i]), i) for i in range(len(vals)) if i not in exclude
        ]
        return max(deltas)[1] if deltas else 0

    def _poll(self) -> None:
        vals = self._read_axes()
        n = len(vals)

        def get_val(ax_key: str, max_key: str, default_idx: int) -> float:
            ax = self._data.get(ax_key)
            idx = ax if ax is not None else default_idx
            v = vals[idx] if idx < n else 0.0
            if ax is not None:
                max_val = self._data.get(max_key)
                if max_val is not None and max_val < 0:
                    v = -v
            return v

        self._stick_l.set_position(
            get_val('axis_yaw', 'yaw_max', 0), get_val('axis_thr', 'thr_max', 1)
        )
        self._stick_r.set_position(
            get_val('axis_roll', 'roll_max', 2), get_val('axis_pitch', 'pitch_max', 3)
        )

        if self._step == _STEP_RELEASE:
            captured = (
                'release_button_index' in self._data
                or 'release_axis_index' in self._data
            )
            if not captured and self._arm_btn_states is not None:
                reserved = self._data.get('arm_button_index')
                for i in range(self._js.get_numbuttons()):
                    if i >= len(self._arm_btn_states):
                        continue
                    if i == reserved:
                        if self._js.get_button(i) != self._arm_btn_states[i]:
                            self._instruction.setText(
                                f'Кнопка {i} уже назначена на ARM.\n\n'
                                'Выберите другую или нажмите «Пропустить».'
                            )
                        continue
                    if self._js.get_button(i) != self._arm_btn_states[i]:
                        self._data['release_type'] = 'button'
                        self._data['release_button_index'] = i
                        self._instruction.setText(
                            f'Кнопка {i} назначена на СБРОС ГРУЗА (канал 6).\n\n'
                            'Нажмите «Далее».'
                        )
                        self._next_btn.setText(f'Далее (кнопка {i})')
                        break
            # тумблеры Radiomaster приходят осями, а не кнопками — ловим и их
            if (
                'release_axis_index' not in self._data
                and 'release_button_index' not in self._data
                and self._arm_axis_states is not None
            ):
                busy = {
                    self._data.get('axis_thr'): 'стик газа',
                    self._data.get('axis_yaw'): 'стик рыскания',
                    self._data.get('axis_pitch'): 'стик тангажа',
                    self._data.get('axis_roll'): 'стик крена',
                    self._data.get('arm_axis_index'): 'ARM',
                }
                for i in range(self._js.get_numaxes()):
                    if i >= len(self._arm_axis_states):
                        continue
                    moved = (self._js.get_axis(i) > 0.5) != self._arm_axis_states[i]
                    if i in busy:
                        if moved:
                            self._instruction.setText(
                                f'Ось {i} уже занята: {busy[i]}.\n\n'
                                'Выберите другую или нажмите «Пропустить».'
                            )
                        continue
                    if moved:
                        self._data['release_type'] = 'axis'
                        self._data['release_axis_index'] = i
                        self._instruction.setText(
                            f'Тумблер (ось {i}) назначен на СБРОС ГРУЗА '
                            '(канал 6).\n\nНажмите «Далее».'
                        )
                        self._next_btn.setText(f'Далее (ось {i})')
                        break

        if self._step == _STEP_ARM:
            arm_captured = (
                'arm_button_index' in self._data or 'arm_axis_index' in self._data
            )
            if not arm_captured:
                if self._arm_btn_states is not None:
                    for i in range(self._js.get_numbuttons()):
                        if self._js.get_button(i) != self._arm_btn_states[i]:
                            self._data['arm_type'] = 'button'
                            self._data['arm_button_index'] = i
                            self._instruction.setText(
                                f'Button {i} captured as ARM/DISARM.\n\nPress "Next".'
                            )
                            self._next_btn.setText(f'Next (button {i})')
                            break
                if (
                    'arm_axis_index' not in self._data
                    and self._arm_axis_states is not None
                ):
                    excluded = {
                        self._data.get('axis_thr'),
                        self._data.get('axis_yaw'),
                        self._data.get('axis_pitch'),
                        self._data.get('axis_roll'),
                    }
                    for i in range(self._js.get_numaxes()):
                        if i in excluded:
                            continue
                        cur_state = self._js.get_axis(i) > 0.5
                        if cur_state != self._arm_axis_states[i]:
                            self._data['arm_type'] = 'axis'
                            self._data['arm_axis_index'] = i
                            self._instruction.setText(
                                f'Axis {i} captured as ARM/DISARM (switch).\n\nPress "Next".'
                            )
                            self._next_btn.setText(f'Next (axis {i})')
                            break

    def _on_next(self) -> None:
        vals = self._read_axes()
        center = self._data.get('center', [0.0] * len(vals))

        if self._step == _STEP_CENTER:
            self._data['center'] = vals
        elif self._step == _STEP_THR_MAX:
            axis = self._detect_axis(vals, set())
            self._data['axis_thr'] = axis
            self._data['thr_max'] = vals[axis]
            self._data['thr_center'] = center[axis]
        elif self._step == _STEP_THR_MIN:
            self._data['thr_min'] = vals[self._data['axis_thr']]
        elif self._step == _STEP_YAW_MAX:
            axis = self._detect_axis(vals, {self._data.get('axis_thr')})
            self._data['axis_yaw'] = axis
            self._data['yaw_max'] = vals[axis]
            self._data['yaw_center'] = center[axis]
        elif self._step == _STEP_YAW_MIN:
            self._data['yaw_min'] = vals[self._data['axis_yaw']]
        elif self._step == _STEP_PITCH_MAX:
            axis = self._detect_axis(
                vals, {self._data.get('axis_thr'), self._data.get('axis_yaw')}
            )
            self._data['axis_pitch'] = axis
            self._data['pitch_max'] = vals[axis]
            self._data['pitch_center'] = center[axis]
        elif self._step == _STEP_PITCH_MIN:
            self._data['pitch_min'] = vals[self._data['axis_pitch']]
        elif self._step == _STEP_ROLL_MAX:
            axis = self._detect_axis(
                vals,
                {
                    self._data.get('axis_thr'),
                    self._data.get('axis_yaw'),
                    self._data.get('axis_pitch'),
                },
            )
            self._data['axis_roll'] = axis
            self._data['roll_max'] = vals[axis]
            self._data['roll_center'] = center[axis]
        elif self._step == _STEP_ROLL_MIN:
            self._data['roll_min'] = vals[self._data['axis_roll']]
        elif self._step == _STEP_ARM:
            if (
                'arm_button_index' not in self._data
                and 'arm_axis_index' not in self._data
            ):
                return
        elif self._step == _STEP_DONE:
            self._build_calibration()
            path = JoystickCalibration.save(
                cast(dict[str, Any], self.calibration), self._joystick_name
            )
            self._poll_timer.stop()
            QMessageBox.information(
                self, 'Калибровка сохранена', f'Настройки джойстика сохранены:\n{path}'
            )
            self.accept()
            return

        self._step += 1
        if self._step in (_STEP_ARM, _STEP_RELEASE):
            pygame.event.pump()
            self._arm_btn_states = [
                self._js.get_button(i) for i in range(self._js.get_numbuttons())
            ]
            self._arm_axis_states = [
                self._js.get_axis(i) > 0.5 for i in range(self._js.get_numaxes())
            ]
        self._next_btn.setText('Далее')
        self._update_ui()

    def _update_ui(self) -> None:
        self._instruction.setText(_STEPS[self._step])
        self._progress.set_current(self._step)
        if self._step == _STEP_RELEASE:
            self._next_btn.setText('Пропустить')
        if self._step == _STEP_DONE:
            self._next_btn.setText('Готово')
            self._instruction.setText(self._summary_text())

    def _summary_text(self) -> str:
        """Что куда назначено — с этой таблицей идут в конфигуратор полётника."""
        from mavixdesktop.joystick.channels import CH_ARM, CH_RELEASE, auto_bindings

        lines = [
            'Калибровка завершена!',
            '',
            f'CH1-4 — стики,  CH{CH_ARM} — ARM',
        ]
        release = self._data.get('release_button_index')
        if isinstance(release, int) and not isinstance(release, bool):
            lines.append(f'CH{CH_RELEASE} — сброс груза (кнопка {release})')
        try:
            bindings = auto_bindings(
                self._data,
                self._js.get_numbuttons(),
                self._js.get_numaxes(),
                self._js.get_numhats(),
            )
        except Exception:
            bindings = []
        for b in bindings:
            lines.append(f'CH{b.channel} — {b.label}')
        if bindings:
            lines += [
                '',
                'Назначить им режимы можно в конфигураторе полётника',
                '(Betaflight / iNav, вкладка Modes).',
            ]
        lines += ['', 'Нажмите «Готово» для сохранения.']
        return '\n'.join(lines)

    def _build_calibration(self) -> None:
        c = self._data
        self.calibration = {
            'axis_thr': c.get('axis_thr', 2),
            'axis_yaw': c.get('axis_yaw', 3),
            'axis_pitch': c.get('axis_pitch', 1),
            'axis_roll': c.get('axis_roll', 0),
            'thr_min': c.get('thr_min', -1.0),
            'thr_max': c.get('thr_max', 1.0),
            'thr_center': c.get('thr_center', 0.0),
            'yaw_min': c.get('yaw_min', -1.0),
            'yaw_max': c.get('yaw_max', 1.0),
            'yaw_center': c.get('yaw_center', 0.0),
            'pitch_min': c.get('pitch_min', -1.0),
            'pitch_max': c.get('pitch_max', 1.0),
            'pitch_center': c.get('pitch_center', 0.0),
            'roll_min': c.get('roll_min', -1.0),
            'roll_max': c.get('roll_max', 1.0),
            'roll_center': c.get('roll_center', 0.0),
            'arm_button_index': c.get('arm_button_index', 0),
            'arm_type': c.get('arm_type', 'button'),
            'arm_axis_index': c.get('arm_axis_index', None),
            'release_type': c.get('release_type', None),
            'release_button_index': c.get('release_button_index', None),
            'release_axis_index': c.get('release_axis_index', None),
        }
        try:
            guid = self._js.get_guid()
        except Exception:
            guid = '00000000000000000000000000000000'
        self.calibration['sdl_gamecontrollerconfig'] = _build_sdl_config(
            self.calibration, self._joystick_name, guid
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        self._poll_timer.stop()
        super().closeEvent(event)
