import json
import subprocess
import time
from typing import Callable

import pygame
from PySide6.QtCore import Qt, QSize, QTimer, Signal, QPoint
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QMessageBox, QFileDialog,
    QScrollArea, QFrame,
)

from mavixdesktop.core.config import settings
from mavixdesktop.ui.style import theme
from mavixdesktop.joystick import calibration as joystick_calibration
from mavixdesktop.joystick.input import JoystickInput
from mavixdesktop.joystick.manager import build_sdl_config, list_joysticks
from .utils import svg_pixmap, AnimatedCard, CardGrid
from .widgets import StickWidget


# Compatibility aliases so the rest of this 800-line legacy screen keeps
# working unchanged. Real ports of these symbols live in mavixdesktop.joystick.
class JoystickManager:
    @staticmethod
    def list_joysticks() -> list[str]:
        return list_joysticks()


class JoystickCalibration:
    @staticmethod
    def save(cal: dict, joystick_name: str):
        return joystick_calibration.save(cal, joystick_name, data_dir=settings.data_path)

    @staticmethod
    def load(joystick_name: str):
        return joystick_calibration.load(joystick_name, data_dir=settings.data_path)

    @staticmethod
    def validate(data: dict) -> tuple[bool, str]:
        return joystick_calibration.validate(data)


_build_sdl_config = build_sdl_config

_STEP_CENTER    = 0
_STEP_THR_MAX   = 1
_STEP_THR_MIN   = 2
_STEP_YAW_MAX   = 3
_STEP_YAW_MIN   = 4
_STEP_PITCH_MAX = 5
_STEP_PITCH_MIN = 6
_STEP_ROLL_MAX  = 7
_STEP_ROLL_MIN  = 8
_STEP_ARM       = 9
_STEP_DONE      = 10

_STEPS = [
    'Шаг 1/10: Установите все стики в ЦЕНТР → Далее',
    'Шаг 2/10: ТЯГА — потяните вверх (МАКСИМУМ) → Далее',
    'Шаг 3/10: ТЯГА — потяните вниз (МИНИМУМ) → Далее',
    'Шаг 4/10: РЫСКАНИЕ — поверните вправо (МАКСИМУМ) → Далее',
    'Шаг 5/10: РЫСКАНИЕ — поверните влево (МИНИМУМ) → Далее',
    'Шаг 6/10: ТАНГАЖ — наклоните стик вперёд (МАКСИМУМ) → Далее',
    'Шаг 7/10: ТАНГАЖ — наклоните стик назад (МИНИМУМ) → Далее',
    'Шаг 8/10: КРЕН — наклоните стик вправо (МАКСИМУМ) → Далее',
    'Шаг 9/10: КРЕН — наклоните стик влево (МИНИМУМ) → Далее',
    'Шаг 10/10: Нажмите кнопку ARM/DISARM на контроллере',
    'Калибровка завершена!\n\nНажмите «Готово» для сохранения.',
]

_CARD_W  = 200
_CARD_H  = 230
_ICON_SZ = 72
_GAP     = 20


class _PopupRow(AnimatedCard):
    _ANIM_DURATION = 200
    _BAR_RADIUS    = theme.RADIUS_SM
    _BAR_HEIGHT    = 2

    def __init__(self, text: str, callback, parent=None):
        super().__init__(parent)
        self.setFixedHeight(42)
        self.setCursor(Qt.PointingHandCursor)
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

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._callback()
        super().mousePressEvent(event)


class _CardMenu(QFrame):
    def __init__(self, items: list, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
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
            row = _PopupRow(text, lambda cb=callback: (cb(), self.close()))
            row.setMinimumWidth(230)
            lay.addWidget(row)
        self.adjustSize()

    def show_at(self, pos):
        self.move(pos)
        self.show()


class JoystickCard(AnimatedCard):
    clicked = Signal(int)
    action  = Signal(int, str)

    def __init__(self, index: int, name: str, calibrated: bool):
        super().__init__()
        self._index = index
        self._active_menu = None  # keep reference to prevent GC while popup is open

        self.setFixedSize(_CARD_W, _CARD_H)
        self.setCursor(Qt.PointingHandCursor)

        self._style_normal = f"""
            QWidget#jsCard {{
                background: {theme.BG_SURFACE};
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
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(6)
        lay.setContentsMargins(12, 18, 12, 14)

        icon_lbl = QLabel()
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setPixmap(svg_pixmap('joystick.svg', _ICON_SZ))

        name_lbl = QLabel(name)
        name_lbl.setAlignment(Qt.AlignCenter)
        name_lbl.setWordWrap(True)
        name_lbl.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; font-size: {theme.FONT_SIZE_SM}px;'
            'font-weight: 600; background: transparent; border: none;'
        )

        status_row = QWidget()
        status_row.setStyleSheet('background: transparent; border: none;')
        sr = QHBoxLayout(status_row)
        sr.setAlignment(Qt.AlignCenter)
        sr.setSpacing(6)
        sr.setContentsMargins(0, 0, 0, 0)

        dot = QLabel('●')
        dot.setStyleSheet(
            f'color: {theme.STATUS_READY if calibrated else theme.STATUS_ERROR}; font-size: 11px;'
            'background: transparent; border: none;'
        )
        status_lbl = QLabel('откалиброван' if calibrated else 'не откалиброван')
        status_lbl.setStyleSheet(
            f'color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE_SM - 3}px;'
            'background: transparent; border: none;'
        )
        sr.addWidget(dot)
        sr.addWidget(status_lbl)

        lay.addWidget(icon_lbl)
        lay.addWidget(name_lbl)
        lay.addWidget(status_row)

        self._menu_btn = QPushButton(self)
        self._menu_btn.setFixedSize(28, 28)
        self._menu_btn.setIcon(QIcon(svg_pixmap('three_dots.svg', 16)))
        self._menu_btn.setIconSize(QSize(16, 16))
        self._menu_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 14px;
            }}
            QPushButton:hover {{
                background: rgba(255,255,255,0.10);
            }}
            QPushButton:pressed {{
                background: rgba(255,255,255,0.05);
            }}
        """)
        self._menu_btn.move(_CARD_W - 28 - 6, 6)
        self._menu_btn.clicked.connect(self.__show_menu)

    def _on_hover(self, hovered: bool):
        self.setStyleSheet(self._style_hover if hovered else self._style_normal)
        self._animate_bar(1000 if hovered else 0)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if not self._menu_btn.geometry().contains(event.pos()):
                self.clicked.emit(self._index)
        super().mousePressEvent(event)

    def __show_menu(self):
        items = [
            ('Загрузить из файла', lambda: self.action.emit(self._index, 'file')),
            ('Калибровка',         lambda: self.action.emit(self._index, 'calibrate')),
            ('Сохранить в файл',   lambda: self.action.emit(self._index, 'file_save')),
        ]
        self._active_menu = _CardMenu(items)
        self._active_menu.show_at(self._menu_btn.mapToGlobal(QPoint(0, self._menu_btn.height())))


class _JoystickGrid(CardGrid):
    CARD_W = _CARD_W
    CARD_H = _CARD_H
    GAP    = _GAP


class _StickPreviewDialog(QDialog):
    """Всплывающее окно — показывает позиции стиков в реальном времени."""

    def __init__(self, joystick_index: int, joystick_name: str,
                 calibration: dict, parent=None, on_takeoff=None):
        super().__init__(parent)
        self._on_takeoff = on_takeoff
        self._joystick_index = joystick_index
        self._calibration = calibration
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
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
            takeoff_btn.setFixedHeight(32)
            takeoff_btn.setStyleSheet(theme.QSS_BUTTON_PRIMARY)
            takeoff_btn.clicked.connect(self.__takeoff)
            root.addWidget(takeoff_btn)

        self._js = JoystickInput(joystick_index, calibration)
        self._timer = QTimer(interval=30)
        self._timer.timeout.connect(self.__poll)
        self._timer.start()

    def __build_title_bar(self, joystick_name: str, root: QVBoxLayout):
        title_row = QHBoxLayout()
        title_lbl = QLabel(joystick_name)
        title_lbl.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; font-size: {theme.FONT_SIZE_SM}px;'
            'font-weight: 600; background: transparent;'
        )
        title_lbl.setWordWrap(False)
        close_btn = QPushButton()
        close_btn.setFixedSize(28, 28)
        close_btn.setIcon(QIcon(svg_pixmap('cross.svg', 14)))
        close_btn.setIconSize(QSize(14, 14))
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 14px;
            }}
            QPushButton:hover {{
                background: rgba(255,80,80,0.20);
            }}
        """)
        close_btn.clicked.connect(self.close)
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        title_row.addWidget(close_btn)
        root.addLayout(title_row)

    def __build_sticks(self, root: QVBoxLayout):
        sticks_row = QHBoxLayout()
        sticks_row.addStretch()
        self._stick_l = StickWidget('Тяга / Рыск.', label_font_px=12)
        self._stick_r = StickWidget('Тангаж / Крен', label_font_px=12)
        sticks_row.addWidget(self._stick_l)
        sticks_row.addSpacing(20)
        sticks_row.addWidget(self._stick_r)
        sticks_row.addStretch()
        root.addLayout(sticks_row)

    def __poll(self):
        try:
            thr, yaw, pitch, roll = self._js.get_stick_positions()
            self._stick_l.set_position(yaw, thr)
            self._stick_r.set_position(roll, pitch)
        except Exception:
            pass

    def __takeoff(self):
        self._timer.stop()
        self.accept()
        if self._on_takeoff:
            self._on_takeoff(self._joystick_index, self._calibration)

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)


class QGCLaunchingOverlay(QDialog):
    """Статус «Открываю QGroundControl…»; закрывается когда окно QGC появилось."""

    def __init__(self, qgc_proc, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setModal(False)
        self.setFixedSize(360, 80)
        self.setStyleSheet(f"""
            QDialog {{
                background: {theme.BG_SURFACE};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS_LG}px;
            }}
        """)

        self.qgc_proc_ = qgc_proc
        self.deadline_ = time.monotonic() + 6.0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lbl = QLabel('Открываю QGroundControl…')
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; font-size: {theme.FONT_SIZE_BASE}px;'
            'font-weight: 600; background: transparent;'
        )
        lay.addWidget(lbl)

        self._timer = QTimer(interval=200)
        self._timer.timeout.connect(self.__check)
        self._timer.start()

    def show_centered(self) -> None:
        screen = QGuiApplication.primaryScreen().geometry()
        x = screen.x() + (screen.width() - self.width()) // 2
        y = screen.y() + (screen.height() - self.height()) // 2
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()

    def __check(self) -> None:
        if self.qgc_proc_.poll() is not None:
            self.close()
            return
        if self.__qgc_window_visible() or time.monotonic() > self.deadline_:
            self.close()

    def __qgc_window_visible(self) -> bool:
        try:
            result = subprocess.run(
                ['wmctrl', '-lp'], capture_output=True, text=True, timeout=1,
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
        pids = {str(self.qgc_proc_.pid)}
        try:
            result = subprocess.run(
                ['pgrep', '-P', str(self.qgc_proc_.pid)],
                capture_output=True, text=True, timeout=1,
            )
            if result.returncode == 0:
                pids.update(result.stdout.split())
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return pids

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)


class JoystickSetupPage(QWidget):
    DEMO_JOYSTICK_NAME = 'Демо-контроллер (Mock)'

    def __init__(self, on_back: Callable, on_takeoff: Callable = None,
                 demo: bool = False):
        super().__init__()
        # None sentinel forces the very first _refresh to populate the UI even
        # when there are zero joysticks (which would otherwise compare equal
        # to an empty list and skip the rebuild path).
        self._joystick_names: list[str] | None = None
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
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._empty = QLabel(
            'Контроллеры не найдены\n\nПодключите джойстик по USB —\nсписок обновится автоматически'
        )
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setStyleSheet(
            f'color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE_BASE}px;'
        )
        self._empty.hide()

        root.addWidget(scroll, 1)
        root.addWidget(self._empty, 1)

        # Auto-rescan pygame joysticks every 3s while the page is visible so a
        # plugged-in controller appears without the user having to hunt for a
        # button. _refresh is idempotent (skips the rebuild if the device list
        # is identical), so polling is cheap.
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.setInterval(3000)
        self._auto_refresh_timer.timeout.connect(self._refresh)

        self._refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self._auto_refresh_timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._auto_refresh_timer.stop()

    def __build_top_bar(self, on_back: Callable) -> QWidget:
        top_bar = QWidget()
        top_bar.setStyleSheet(
            f'background: {theme.BG_SURFACE}; border-bottom: 1px solid {theme.BORDER};'
        )
        top_bar.setFixedHeight(60)
        tb = QHBoxLayout(top_bar)
        tb.setContentsMargins(16, 0, 28, 0)
        tb.setSpacing(12)

        back_btn = QPushButton()
        back_btn.setFixedSize(theme.OVERLAY_BTN_CORNER, theme.OVERLAY_BTN_CORNER)
        back_btn.setIcon(QIcon(svg_pixmap('arrow_back.svg', theme.OVERLAY_BTN_CORNER_ICON)))
        back_btn.setIconSize(QSize(theme.OVERLAY_BTN_CORNER_ICON, theme.OVERLAY_BTN_CORNER_ICON))
        back_btn.setStyleSheet(f"""
            QPushButton {{
                background: {theme.BG_INPUT};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.OVERLAY_BTN_CORNER // 2}px;
            }}
            QPushButton:hover {{
                background: rgba(42,130,218,0.30);
                border-color: {theme.ACCENT};
            }}
            QPushButton:pressed {{
                background: rgba(31,106,176,0.50);
            }}
        """)
        back_btn.setToolTip('Назад к экрану дрона')
        back_btn.clicked.connect(on_back)

        title = QLabel('Выбор джойстика')
        title.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; font-size: {theme.FONT_SIZE_LG}px;'
            'font-weight: 700; background: transparent; border: none;'
        )

        tb.addWidget(back_btn)
        tb.addWidget(title)
        tb.addStretch()
        return top_bar

    def set_fc_type(self, fc_type: str):
        self._fc_type = fc_type

    def _refresh(self):
        # В демо-режиме pygame.joystick.get_count() вернёт 0 на машине
        # без подключённого контроллера. Подсовываем один мок-имя, чтобы
        # UI было что показать. Реальные взаимодействия с pygame в
        # демо-режиме перехватываются ниже (см. _on_card_clicked /
        # _on_card_action).
        if self._demo:
            names = [self.DEMO_JOYSTICK_NAME]
        else:
            names = JoystickManager.list_joysticks()

        # Auto-refresh tick: skip the rebuild if the device list hasn't changed,
        # so we don't churn QWidget children (and stomp on any open menu) 3x/sec.
        if names == self._joystick_names:
            return
        self._joystick_names = names

        if not self._joystick_names:
            self._empty.show()
            self._grid.hide()
            self._grid.set_cards([])
            return

        self._empty.hide()
        self._grid.show()

        cards = []
        for i, name in enumerate(self._joystick_names):
            cal = JoystickCalibration.load(name)
            card = JoystickCard(i, name, calibrated=bool(cal))
            card.clicked.connect(self._on_card_clicked)
            card.action.connect(self._on_card_action)
            cards.append(card)
        self._grid.set_cards(cards)

    def _on_card_clicked(self, index: int):
        if self._demo:
            QMessageBox.information(
                self, 'Демо-режим',
                'Калибровка и подключение реального джойстика недоступны в демо-режиме.'
            )
            return
        name = self._joystick_names[index]
        takeoff_cb = self._on_takeoff if self._fc_type in ('crsf', 'mavlink') else None
        saved = JoystickCalibration.load(name)
        if saved:
            dlg = _StickPreviewDialog(index, name, saved, parent=self,
                                      on_takeoff=takeoff_cb)
            dlg.exec()
        else:
            cal_dlg = JoystickCalibrationDialog(index, name, parent=self)
            if cal_dlg.exec() == QDialog.Accepted and cal_dlg.calibration:
                self._refresh()
                dlg = _StickPreviewDialog(index, name, cal_dlg.calibration, parent=self,
                                          on_takeoff=takeoff_cb)
                dlg.exec()

    def _on_card_action(self, index: int, action: str):
        if self._demo:
            QMessageBox.information(
                self, 'Демо-режим',
                'Действия с реальным джойстиком недоступны в демо-режиме.'
            )
            return
        name = self._joystick_names[index]
        if action == 'file':
            self._load_from_file(index, name)
        elif action == 'calibrate':
            dlg = JoystickCalibrationDialog(index, name, parent=self)
            if dlg.exec() == QDialog.Accepted and dlg.calibration:
                self._refresh()
        elif action == 'file_save':
            self._save_to_file(index, name)

    def _load_from_file(self, index: int, name: str):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Загрузить калибровку', '', 'JSON (*.json)'
        )
        if not path:
            return
        try:
            with open(path, 'r') as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, 'Ошибка чтения файла', str(e))
            return
        ok, msg = JoystickCalibration.validate(data)
        if not ok:
            QMessageBox.critical(self, 'Неверный формат калибровки', msg)
            return
        JoystickCalibration.save(data, name)
        self._refresh()
        QMessageBox.information(
            self, 'Калибровка загружена',
            f'Калибровка для «{name}» успешно загружена и сохранена.'
        )

    def _save_to_file(self, index: int, name: str):
        cal = JoystickCalibration.load(name)
        if not cal:
            QMessageBox.warning(self, 'Нет калибровки',
                                f'Джойстик «{name}» не откалиброван.')
            return
        path, _ = QFileDialog.getSaveFileName(
            self, 'Сохранить калибровку', f'{name}.json', 'JSON (*.json)'
        )
        if not path:
            return
        try:
            with open(path, 'w') as f:
                json.dump(cal, f, indent=2, ensure_ascii=False)
        except Exception as e:
            QMessageBox.critical(self, 'Ошибка сохранения', str(e))
            return
        QMessageBox.information(self, 'Сохранено',
                                f'Калибровка сохранена в:\n{path}')


class JoystickCalibrationDialog(QDialog):
    def __init__(self, joystick_index: int, joystick_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Калибровка джойстика')
        self.setMinimumWidth(460)
        self._step = 0
        self._data: dict = {}
        self._joystick_name = joystick_name
        self.calibration: dict = None
        self._arm_btn_states: list | None = None
        self._arm_axis_states: list | None = None

        pygame.joystick.init()
        self._js = pygame.joystick.Joystick(joystick_index)
        self._js.init()

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        sticks_row = QHBoxLayout()
        sticks_row.addStretch()
        self._stick_l = StickWidget('Рыскание/Тяга', label_font_px=18)
        self._stick_r = StickWidget('Крен/Тангаж', label_font_px=18)
        sticks_row.addWidget(self._stick_l)
        sticks_row.addSpacing(16)
        sticks_row.addWidget(self._stick_r)
        sticks_row.addStretch()
        layout.addLayout(sticks_row)

        self._instruction = QLabel()
        self._instruction.setWordWrap(True)
        self._instruction.setAlignment(Qt.AlignCenter)
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

    def _detect_axis(self, vals: list[float], exclude: set) -> int:
        center = self._data.get('center', [0.0] * len(vals))
        deltas = [(abs(vals[i] - center[i]), i) for i in range(len(vals)) if i not in exclude]
        return max(deltas)[1] if deltas else 0

    def _poll(self):
        vals = self._read_axes()
        n = len(vals)

        def get_val(ax_key, max_key, default_idx):
            ax = self._data.get(ax_key)
            idx = ax if ax is not None else default_idx
            v = vals[idx] if idx < n else 0.0
            if ax is not None:
                max_val = self._data.get(max_key)
                if max_val is not None and max_val < 0:
                    v = -v
            return v

        self._stick_l.set_position(get_val('axis_yaw', 'yaw_max', 0),
                                   get_val('axis_thr', 'thr_max', 1))
        self._stick_r.set_position(get_val('axis_roll', 'roll_max', 2),
                                   get_val('axis_pitch', 'pitch_max', 3))

        if self._step == _STEP_ARM:
            arm_captured = 'arm_button_index' in self._data or 'arm_axis_index' in self._data
            if not arm_captured:
                if self._arm_btn_states is not None:
                    for i in range(self._js.get_numbuttons()):
                        if self._js.get_button(i) != self._arm_btn_states[i]:
                            self._data['arm_type'] = 'button'
                            self._data['arm_button_index'] = i
                            self._instruction.setText(
                                f'Кнопка {i} захвачена как ARM/DISARM.\n\nНажмите «Далее».'
                            )
                            self._next_btn.setText(f'Далее (кнопка {i})')
                            break
                if 'arm_axis_index' not in self._data and self._arm_axis_states is not None:
                    excluded = {
                        self._data.get('axis_thr'), self._data.get('axis_yaw'),
                        self._data.get('axis_pitch'), self._data.get('axis_roll'),
                    }
                    for i in range(self._js.get_numaxes()):
                        if i in excluded:
                            continue
                        cur_state = self._js.get_axis(i) > 0.5
                        if cur_state != self._arm_axis_states[i]:
                            self._data['arm_type'] = 'axis'
                            self._data['arm_axis_index'] = i
                            self._instruction.setText(
                                f'Ось {i} захвачена как ARM/DISARM (тумблер).\n\nНажмите «Далее».'
                            )
                            self._next_btn.setText(f'Далее (ось {i})')
                            break

    def _on_next(self):
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
            axis = self._detect_axis(vals, {self._data.get('axis_thr'), self._data.get('axis_yaw')})
            self._data['axis_pitch'] = axis
            self._data['pitch_max'] = vals[axis]
            self._data['pitch_center'] = center[axis]
        elif self._step == _STEP_PITCH_MIN:
            self._data['pitch_min'] = vals[self._data['axis_pitch']]
        elif self._step == _STEP_ROLL_MAX:
            axis = self._detect_axis(vals, {self._data.get('axis_thr'), self._data.get('axis_yaw'),
                                            self._data.get('axis_pitch')})
            self._data['axis_roll'] = axis
            self._data['roll_max'] = vals[axis]
            self._data['roll_center'] = center[axis]
        elif self._step == _STEP_ROLL_MIN:
            self._data['roll_min'] = vals[self._data['axis_roll']]
        elif self._step == _STEP_ARM:
            if 'arm_button_index' not in self._data and 'arm_axis_index' not in self._data:
                return
        elif self._step == _STEP_DONE:
            self._build_calibration()
            path = JoystickCalibration.save(self.calibration, self._joystick_name)
            self._poll_timer.stop()
            QMessageBox.information(
                self, 'Калибровка сохранена',
                f'Настройки джойстика сохранены:\n{path}'
            )
            self.accept()
            return

        self._step += 1
        if self._step == _STEP_ARM:
            pygame.event.pump()
            self._arm_btn_states = [self._js.get_button(i) for i in range(self._js.get_numbuttons())]
            self._arm_axis_states = [self._js.get_axis(i) > 0.5 for i in range(self._js.get_numaxes())]
        self._next_btn.setText('Далее')
        self._update_ui()

    def _update_ui(self):
        self._instruction.setText(_STEPS[self._step])
        if self._step == _STEP_DONE:
            self._next_btn.setText('Готово')

    def _build_calibration(self):
        c = self._data
        self.calibration = {
            'axis_thr':   c.get('axis_thr',   2),
            'axis_yaw':   c.get('axis_yaw',   3),
            'axis_pitch': c.get('axis_pitch', 1),
            'axis_roll':  c.get('axis_roll',  0),
            'thr_min':    c.get('thr_min',   -1.0),
            'thr_max':    c.get('thr_max',    1.0),
            'thr_center': c.get('thr_center', 0.0),
            'yaw_min':    c.get('yaw_min',   -1.0),
            'yaw_max':    c.get('yaw_max',    1.0),
            'yaw_center': c.get('yaw_center', 0.0),
            'pitch_min':    c.get('pitch_min',   -1.0),
            'pitch_max':    c.get('pitch_max',    1.0),
            'pitch_center': c.get('pitch_center', 0.0),
            'roll_min':    c.get('roll_min',   -1.0),
            'roll_max':    c.get('roll_max',    1.0),
            'roll_center': c.get('roll_center', 0.0),
            'arm_button_index': c.get('arm_button_index', 0),
            'arm_type':         c.get('arm_type', 'button'),
            'arm_axis_index':   c.get('arm_axis_index', None),
        }
        try:
            guid = self._js.get_guid()
        except Exception:
            guid = '00000000000000000000000000000000'
        self.calibration['sdl_gamecontrollerconfig'] = _build_sdl_config(
            self.calibration, self._joystick_name, guid
        )

    def closeEvent(self, event):
        self._poll_timer.stop()
        super().closeEvent(event)
