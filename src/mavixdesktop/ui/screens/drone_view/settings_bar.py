"""Bottom settings bar for the drone view."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QModelIndex, QObject, QPoint, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from mavixdesktop.ui.screens.utils import svg_pixmap
from mavixdesktop.ui.style import theme


class _PopupItemDelegate(QStyledItemDelegate):
    _HIGHLIGHT_BG = QColor(34, 211, 238, 30)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._hover_index = QModelIndex()

    def set_hover_index(self, index: QModelIndex) -> None:
        self._hover_index = QModelIndex(index) if index is not None else QModelIndex()

    def paint(self, painter: QPainter, option: QStyleOptionViewItem,
              index: QModelIndex) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        is_selected = bool(option.state & QStyle.State_Selected)
        is_hover = (self._hover_index.isValid()
                    and self._hover_index.row() == index.row())
        is_active = is_selected or is_hover

        if is_active:
            painter.fillRect(option.rect, self._HIGHLIGHT_BG)

        text = str(index.data(Qt.DisplayRole) or '')
        text_rect = option.rect.adjusted(12, 0, -12, 0)
        text_color = QColor(theme.ACCENT) if is_active else QColor(theme.TEXT_PRIMARY)
        painter.setPen(text_color)
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, text)
        painter.restore()


class _HoverTracker(QObject):
    def __init__(self, view: QWidget, delegate: _PopupItemDelegate) -> None:
        super().__init__(view)
        self._view = view
        self._delegate = delegate

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.MouseMove:
            try:
                pos = event.position().toPoint()
            except AttributeError:
                pos = event.pos()
            index = self._view.indexAt(pos)
            self._delegate.set_hover_index(index)
            self._view.viewport().update()
        elif event.type() in (QEvent.Leave, QEvent.HoverLeave):
            self._delegate.set_hover_index(QModelIndex())
            self._view.viewport().update()
        return False


class _BoundedComboBox(QComboBox):
    _POPUP_VIEW_QSS = f"""
        QAbstractItemView, QListView {{
            background: {theme.BG_INPUT};
            color: {theme.TEXT_PRIMARY};
            border: 1px solid {theme.BORDER};
            outline: none;
            padding: 4px;
            selection-background-color: {theme.ACCENT_SUBTLE};
            selection-color: {theme.ACCENT};
        }}
        QAbstractItemView::item, QListView::item {{
            padding: 7px 12px;
            border-radius: {theme.RADIUS_SM}px;
            background: transparent;
            color: {theme.TEXT_PRIMARY};
        }}
        QAbstractItemView::item:hover, QListView::item:hover {{
            background: {theme.ACCENT_SUBTLE};
            color: {theme.ACCENT};
        }}
        QAbstractItemView::item:selected, QListView::item:selected {{
            background: {theme.ACCENT_SUBTLE};
            color: {theme.ACCENT};
        }}
    """

    _POPUP_CONTAINER_QSS = f"""
        QWidget {{
            background: {theme.BG_INPUT};
            border: 1px solid {theme.BORDER};
        }}
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._popup_delegate = _PopupItemDelegate(self)
        self.view().setItemDelegate(self._popup_delegate)
        self._hover_tracker = _HoverTracker(self.view(), self._popup_delegate)
        self.view().viewport().installEventFilter(self._hover_tracker)
        self._restyle_popup()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(theme.TEXT_MUTED), 1.5)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        r = self.rect()
        cx = r.right() - 12
        cy = r.center().y()
        p.drawLine(cx - 4, cy - 2, cx, cy + 2)
        p.drawLine(cx, cy + 2, cx + 4, cy - 2)
        p.end()

    def _restyle_popup(self) -> None:
        view = self.view()
        if view is None:
            return
        view.setMouseTracking(True)
        view.setAttribute(Qt.WA_Hover, True)
        viewport = view.viewport()
        if viewport is not None:
            viewport.setMouseTracking(True)
            viewport.setAttribute(Qt.WA_Hover, True)
        view.setStyleSheet(self._POPUP_VIEW_QSS)
        container = view.parentWidget()
        if container is not None and container is not view:
            container.setAttribute(Qt.WA_StyledBackground, True)
            container.setStyleSheet(self._POPUP_CONTAINER_QSS)

    def showPopup(self) -> None:
        super().showPopup()
        self._restyle_popup()
        popup = self.view().window() if self.view() is not None else None
        app_win = self.window()
        if popup is None or app_win is None:
            return
        popup_geom = popup.geometry()
        field_top_global = self.mapToGlobal(QPoint(0, 0))
        new_y = field_top_global.y() - popup_geom.height()
        win_top_global = app_win.mapToGlobal(QPoint(0, 0))
        new_y = max(new_y, win_top_global.y())
        popup.move(popup_geom.x(), new_y)


class SettingsBar(QWidget):
    def __init__(self, on_save: Callable[[], None],
                 on_calibrate: Callable[[], None]) -> None:
        super().__init__()
        self.setObjectName('settingsBar')
        self.setStyleSheet(f"""
            QWidget#settingsBar {{
                background: {theme.BG_SURFACE};
                border-top: 1px solid {theme.BORDER};
            }}
            QWidget#settingsBar QComboBox,
            QWidget#settingsBar QLineEdit {{
                background: {theme.BG_INPUT};
                color: {theme.TEXT_PRIMARY};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS_MD}px;
                padding: 6px 24px 6px 10px;
                font-size: {theme.FONT_SIZE_SM}px;
            }}
            QWidget#settingsBar QComboBox:hover,
            QWidget#settingsBar QLineEdit:hover {{
                background: rgba(42, 130, 218, 0.20);
            }}
            QWidget#settingsBar QComboBox:focus,
            QWidget#settingsBar QLineEdit:focus {{
                border-color: {theme.ACCENT};
            }}
            QWidget#settingsBar QComboBox QAbstractItemView {{
                background: {theme.BG_INPUT};
                color: {theme.TEXT_PRIMARY};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS_MD}px;
                outline: none;
                padding: 4px;
                selection-background-color: {theme.ACCENT_SUBTLE};
                selection-color: {theme.ACCENT};
            }}
            QWidget#settingsBar QComboBox QAbstractItemView::item {{
                padding: 7px 12px;
                border-radius: {theme.RADIUS_SM}px;
            }}
            QWidget#settingsBar QComboBox QAbstractItemView::item:hover {{
                background: {theme.ACCENT_SUBTLE};
                color: {theme.ACCENT};
            }}
        """)
        self.setFixedHeight(72)

        self._params: list = []
        self.__build(on_save, on_calibrate)

    def __build(self, on_save: Callable[[], None],
                on_calibrate: Callable[[], None]) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(10)

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

        layout.addWidget(self.__muted('Разрешение'))
        self.resolution_box = _BoundedComboBox()
        self.resolution_box.setMinimumWidth(140)
        self.resolution_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.resolution_box.currentIndexChanged.connect(self._on_resolution_changed)
        self.resolution_box.setCursor(Qt.PointingHandCursor)
        self.resolution_box.view().setCursor(Qt.PointingHandCursor)
        layout.addWidget(self.resolution_box)

        layout.addWidget(self.__muted('FPS'))
        self.fps_box = _BoundedComboBox()
        self.fps_box.setMinimumWidth(70)
        self.fps_box.setCursor(Qt.PointingHandCursor)
        self.fps_box.view().setCursor(Qt.PointingHandCursor)
        layout.addWidget(self.fps_box)

        layout.addWidget(self.__muted('Битрейт'))
        self.bitrate_input = QLineEdit()
        self.bitrate_input.setPlaceholderText('kbps')
        self.bitrate_input.setFixedWidth(80)
        self.bitrate_input.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self.bitrate_input)

        self.calibrate_btn = QPushButton('⟳ Калибровка камер')
        self.calibrate_btn.setFixedHeight(36)
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

        self.save_btn = QPushButton()
        self.save_btn.setFixedSize(40, 40)
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(on_save)
        self.save_btn.setIcon(QIcon(svg_pixmap('save.svg', 28, color=theme.TEXT_PRIMARY)))
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

    def update_fc_status(self, fc_type: str, fc_name: str) -> None:
        if not fc_type or fc_type == 'none':
            self.fc_status_label.setText('FC: Не подключён')
        elif fc_type == 'crsf':
            self.fc_status_label.setText(f'FC: {fc_name} (CRSF)')
        elif fc_type == 'mavlink':
            self.fc_status_label.setText(f'FC: {fc_name} (MAVLink)')
        self.warn_label.setVisible(fc_type == 'crsf')

    def update_camera(self, camera: dict) -> None:
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

    def _fill_fps(self, resolution: tuple[int, int] | None, cur_param: dict | None) -> None:
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

    def _on_resolution_changed(self, _: int) -> None:
        res = self.resolution_box.currentData()
        if res:
            self._fill_fps(res, None)

    def get_selected_params(self):
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
