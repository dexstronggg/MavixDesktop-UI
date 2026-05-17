"""Нижняя панель настроек дрон-вью.

Содержит:
  - статус FC и предупреждение о смене настроек в полёте
  - выбор разрешения, FPS, битрейта камеры
  - кнопку и результаты спидтеста
  - кнопку сохранения настроек
"""
from typing import Callable

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QLineEdit,
)

from mavixdesktop.ui.style import theme
from mavixdesktop.ui.screens.utils import svg_pixmap


class SettingsBar(QWidget):
    """Панель с настройками камеры, статусом FC и спидтестом.

    Публичный API
    -------------
    update_fc_status(fc_type, fc_name) : обновить статус FC
    update_ping(rtt_ms)                : обновить показание peer-to-peer пинга
    update_camera(camera)              : заполнить дропдауны параметрами камеры
    get_selected_params()              : → (param_index, bitrate) или (None, None)
    """

    def __init__(self, on_save: Callable, on_calibrate: Callable):
        super().__init__()
        self.setStyleSheet(
            f'background: {theme.BG_SURFACE}; border-top: 1px solid {theme.BORDER};'
        )
        self.setFixedHeight(72)

        self._params = []
        self.__build(on_save, on_calibrate)

    def __build(self, on_save: Callable, on_calibrate: Callable):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(10)

        # ── Левая часть: FC-статус и предупреждение ───────────────────────────
        self.fc_status_label = QLabel('FC: Не подключён')
        self.fc_status_label.setStyleSheet(
            f'color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE_SM}px;'
            'background: transparent;'
        )

        self.warn_label = QLabel('⚠  Смена настроек во время полёта недоступна')
        self.warn_label.setStyleSheet(
            f'color: {theme.WARNING};'
            f'font-size: {theme.FONT_SIZE_SM - 2}px;'
            'background: transparent;'
        )
        self.warn_label.hide()

        layout.addWidget(self.fc_status_label)
        layout.addStretch()
        layout.addWidget(self.warn_label)
        layout.addStretch()

        # ── Правая часть: настройки камеры ────────────────────────────────────
        layout.addWidget(self.__muted('Разрешение'))
        self.resolution_box = QComboBox()
        self.resolution_box.setMinimumWidth(140)
        self.resolution_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.resolution_box.currentIndexChanged.connect(self._on_resolution_changed)
        layout.addWidget(self.resolution_box)

        layout.addWidget(self.__muted('FPS'))
        self.fps_box = QComboBox()
        self.fps_box.setMinimumWidth(70)
        layout.addWidget(self.fps_box)

        layout.addWidget(self.__muted('Битрейт'))
        self.bitrate_input = QLineEdit()
        self.bitrate_input.setPlaceholderText('kbps')
        self.bitrate_input.setFixedWidth(80)
        layout.addWidget(self.bitrate_input)

        # ── Кнопка принудительной калибровки камер ────────────────────────────
        self.calibrate_btn = QPushButton('⟳ Калибровка камер')
        self.calibrate_btn.setFixedHeight(36)
        self.calibrate_btn.setToolTip('Полная пересборка калибровки всех камер')
        self.calibrate_btn.setStyleSheet(f"""
            QPushButton {{
                background: {theme.BG_INPUT};
                color: {theme.TEXT_PRIMARY};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS_MD}px;
                padding: 0 12px;
                font-size: {theme.FONT_SIZE_SM}px;
            }}
            QPushButton:hover {{
                background: rgba(42,130,218,0.20);
                border-color: {theme.ACCENT};
            }}
            QPushButton:pressed {{
                background: rgba(42,130,218,0.35);
            }}
        """)
        self.calibrate_btn.clicked.connect(on_calibrate)
        layout.addWidget(self.calibrate_btn)
        layout.addSpacing(6)

        # ── Кнопка сохранения ─────────────────────────────────────────────────
        self.save_btn = QPushButton()
        self.save_btn.setFixedSize(40, 40)
        self.save_btn.setToolTip('Сохранить настройки камеры')
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(on_save)
        self.save_btn.setIcon(QIcon(svg_pixmap('save.svg', 28)))
        self.save_btn.setIconSize(QSize(22, 22))
        self.save_btn.setStyleSheet(f"""
            QPushButton {{
                background: {theme.BG_INPUT};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS_MD}px;
            }}
            QPushButton:enabled {{
                border-color: {theme.ACCENT};
                background: {theme.BG_INPUT};
            }}
            QPushButton:enabled:hover {{
                background: rgba(42,130,218,0.18);
            }}
            QPushButton:enabled:pressed {{
                background: rgba(42,130,218,0.32);
            }}
            QPushButton:disabled {{
                opacity: 0.35;
            }}
        """)
        layout.addWidget(self.save_btn)

    @staticmethod
    def __muted(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f'color: {theme.TEXT_MUTED};'
            f'font-size: {theme.FONT_SIZE_SM - 1}px;'
            'background: transparent;'
        )
        return lbl

    # ── FC и спидтест ─────────────────────────────────────────────────────────

    def update_fc_status(self, fc_type: str, fc_name: str):
        """Обновить текст статуса FC."""
        if not fc_type or fc_type == 'none':
            self.fc_status_label.setText('FC: Не подключён')
        elif fc_type == 'crsf':
            self.fc_status_label.setText(f'FC: {fc_name} (CRSF)')
        elif fc_type == 'mavlink':
            self.fc_status_label.setText(f'FC: {fc_name} (MAVLink)')
        self.warn_label.setVisible(fc_type == 'crsf')

    # ── Настройки камеры ──────────────────────────────────────────────────────

    def update_camera(self, camera: dict):
        """Заполнить дропдауны разрешения/FPS по конфигу камеры."""
        self._params = camera.get('params', [])
        param_index = camera.get('param_index', 0)
        bitrate = camera.get('bitrate_kbs', 1000)

        seen, resolutions = set(), []
        for p in self._params:
            key = (p['width'], p['height'])
            if key not in seen:
                seen.add(key)
                resolutions.append(key)
        resolutions.sort(key=lambda r: r[1], reverse=True)

        cur_param = self._params[param_index] if param_index < len(self._params) else None
        cur_res = (cur_param['width'], cur_param['height']) if cur_param else None

        self.resolution_box.blockSignals(True)
        self.resolution_box.clear()
        cur_res_idx = 0
        for i, (w, h) in enumerate(resolutions):
            self.resolution_box.addItem(f'{w}×{h}', (w, h))
            if (w, h) == cur_res:
                cur_res_idx = i
        self.resolution_box.setCurrentIndex(cur_res_idx)
        self.resolution_box.blockSignals(False)

        self._fill_fps(cur_res, cur_param)
        self.bitrate_input.setText(str(bitrate))
        self.save_btn.setEnabled(True)

    def _fill_fps(self, resolution, cur_param):
        if resolution is None:
            return
        w, h = resolution
        fps_list = sorted(
            {p['fps'] for p in self._params if p['width'] == w and p['height'] == h},
            reverse=True,
        )
        cur_fps = cur_param['fps'] if cur_param else None
        self.fps_box.blockSignals(True)
        self.fps_box.clear()
        cur_fps_idx = 0
        for i, fps in enumerate(fps_list):
            self.fps_box.addItem(str(fps), fps)
            if fps == cur_fps:
                cur_fps_idx = i
        self.fps_box.setCurrentIndex(cur_fps_idx)
        self.fps_box.blockSignals(False)

    def _on_resolution_changed(self, _):
        res = self.resolution_box.currentData()
        if res:
            self._fill_fps(res, None)

    def get_selected_params(self):
        """Вернуть (param_index, bitrate_kbs) по текущему выбору или (None, None)."""
        res = self.resolution_box.currentData()
        fps = self.fps_box.currentData()
        if res is None or fps is None:
            return None, None
        w, h = res
        for i, p in enumerate(self._params):
            if p['width'] == w and p['height'] == h and p['fps'] == fps:
                try:
                    bitrate = int(self.bitrate_input.text())
                except ValueError:
                    bitrate = 1000
                return i, bitrate
        return None, None
