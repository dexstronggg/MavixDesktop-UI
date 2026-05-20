"""Нижняя панель настроек дрон-вью.

Содержит:
  - статус FC и предупреждение о смене настроек в полёте
  - выбор разрешения, FPS, битрейта камеры
  - кнопку и результаты спидтеста
  - кнопку сохранения настроек
"""
from typing import Callable

from PySide6.QtCore import QSize, QPoint, Qt, QObject, QEvent, QModelIndex
from PySide6.QtGui import QIcon, QPainter, QPen, QColor
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QLineEdit, QStyle, QStyledItemDelegate,
)

from mavixdesktop.ui.style import theme
from mavixdesktop.ui.screens.utils import svg_pixmap


class _PopupItemDelegate(QStyledItemDelegate):
    """Делегат для popup'а combobox'а — рисует hover вручную.

    QSS-правило ``QAbstractItemView::item:hover`` не срабатывает в
    комбинации QListView + Fusion + scoped stylesheet: предыдущие
    попытки через mouseTracking и WA_Hover не дали эффекта (Qt style
    engine берёт State_MouseOver не у того виджета, либо переопределяет
    цвет через свою палитру). Здесь рисуем hover/selected напрямую:
    fillRect под item'ом и pen цветом ACCENT — минуя style engine.

    Hover-index трекается через :class:`_HoverTracker` event-filter
    на viewport: на каждый MouseMove запоминаем index под курсором,
    зовём viewport.update() — paint() перерисовывает с подсветкой.
    """

    # Заливка hover/selected — rgba от theme.ACCENT (#22d3ee) с alpha
    # ~30/255 (≈ 0.12) совпадает по визуальному весу с theme.ACCENT_SUBTLE
    # в QSS, но через QColor — на этот раз гарантированно.
    _HIGHLIGHT_BG = QColor(34, 211, 238, 30)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover_index = QModelIndex()

    def set_hover_index(self, index: QModelIndex) -> None:
        self._hover_index = QModelIndex(index) if index is not None else QModelIndex()

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        is_selected = bool(option.state & QStyle.State_Selected)
        is_hover = (self._hover_index.isValid()
                    and self._hover_index.row() == index.row())
        is_active = is_selected or is_hover

        if is_active:
            painter.fillRect(option.rect, self._HIGHLIGHT_BG)

        text = str(index.data(Qt.DisplayRole) or '')
        # Padding 12px по горизонтали — совпадает с padding из
        # _POPUP_VIEW_QSS чтобы текст не «прыгал» между состояниями.
        text_rect = option.rect.adjusted(12, 0, -12, 0)
        text_color = QColor(theme.ACCENT) if is_active else QColor(theme.TEXT_PRIMARY)
        painter.setPen(text_color)
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, text)
        painter.restore()


class _HoverTracker(QObject):
    """Event-filter на viewport popup-вью: трекает индекс под курсором и
    форсит перерисовку через viewport.update(). Делегат читает индекс
    при следующем paint() и красит hover.
    """

    def __init__(self, view, delegate: _PopupItemDelegate):
        super().__init__(view)
        self._view = view
        self._delegate = delegate

    def eventFilter(self, obj, event):
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
    """QComboBox с двумя кастомизациями:

    1. **Стиль popup'а напрямую на view и контейнере.** На Windows Qt
       выносит popup в отдельное top-level окно, у которого свой
       нативный painter — QSS-цепочка от родительского комбобокса/
       SettingsBar не достигает фона этого окна, и popup рендерится
       серым на тёмной теме. Здесь форсим setStyleSheet на самом
       view и на его parentWidget (контейнер popup'а), включая
       WA_StyledBackground для гарантии что Qt будет красить фон.

    2. **Удержание popup'а в границах application window.** Qt по
       умолчанию ориентируется на экран, не на окно. Если поле в самом
       низу окна, popup уходит за нижнюю границу. После super().showPopup
       сверяем геометрию и при необходимости поднимаем popup над полем.

    Логику самого комбобокса не трогаем — только стили и позиционирование.
    """

    # Стиль самого QListView внутри popup'а — bg, padding, hover/selected
    # элементов. Применяется в __init__ через self.view().setStyleSheet —
    # это обходит QSS-цепочку, которая не доходит до popup-окна.
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

    # Стиль контейнера popup'а (QComboBoxPrivateContainer) — отдельного
    # top-level окна-обёртки вокруг view. Без этого его дефолтный
    # системный фон проступает между бордером и items как «серая плашка».
    _POPUP_CONTAINER_QSS = f"""
        QWidget {{
            background: {theme.BG_INPUT};
            border: 1px solid {theme.BORDER};
        }}
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Кастомный делегат + tracker для надёжного hover-painting.
        # QSS-route оказался ненадёжным (см. _PopupItemDelegate docstring).
        self._popup_delegate = _PopupItemDelegate(self)
        self.view().setItemDelegate(self._popup_delegate)
        self._hover_tracker = _HoverTracker(self.view(), self._popup_delegate)
        self.view().viewport().installEventFilter(self._hover_tracker)
        self._restyle_popup()

    def paintEvent(self, event):
        """Рисуем стандартный QComboBox, а сверху — chevron-down справа
        как визуальный индикатор «это раскрывающийся список».

        Используем QPainter вместо background-image в QSS: не зависим от
        SVG-ресурсов и от дефолтного Fusion-painter'а (рисующего жирный
        треугольник в неподходящем стиле). Right-padding 24px в scoped
        QSS оставляет место чтобы text combobox'а не лез под chevron.
        """
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(theme.TEXT_MUTED), 1.5)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        r = self.rect()
        cx = r.right() - 12  # 12px от правого края
        cy = r.center().y()
        # ⌄ chevron: две линии 4px каждая, вершина внизу
        p.drawLine(cx - 4, cy - 2, cx, cy + 2)
        p.drawLine(cx, cy + 2, cx + 4, cy - 2)
        p.end()

    def _restyle_popup(self):
        """Применить наши стили к view и контейнеру popup'а. Вызывается
        и в __init__, и в showPopup — контейнер создаётся Qt лениво,
        и при __init__ его ещё может не существовать.

        Дополнительно включаем mouseTracking + WA_Hover на view и его
        viewport — без этого QStyle::State_MouseOver не ставится у
        item'а под курсором, и правило ``QAbstractItemView::item:hover``
        в QSS не триггерится (QListView по дефолту tracking выключен).
        """
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

    def showPopup(self):
        super().showPopup()
        # Контейнер popup'а мог только что появиться — перекрашиваем.
        self._restyle_popup()
        popup = self.view().window() if self.view() is not None else None
        app_win = self.window()
        if popup is None or app_win is None:
            return
        popup_geom = popup.geometry()
        # Всегда ставим popup НАД полем. Раньше тут был условный flip
        # «если вышел за нижнюю границу окна — флипаем», но это давало
        # непоследовательное поведение: в зависимости от позиции окна
        # на экране Qt сам ставил popup то вниз, то вверх, и оператор
        # видел разные направления для одной и той же UI-операции.
        field_top_global = self.mapToGlobal(QPoint(0, 0))
        new_y = field_top_global.y() - popup_geom.height()
        # Если над полем места не хватает (popup выше application
        # window) — упираем в верхнюю границу окна, иначе уйдёт за
        # title-bar и потеряет видимость.
        win_top_global = app_win.mapToGlobal(QPoint(0, 0))
        new_y = max(new_y, win_top_global.y())
        popup.move(popup_geom.x(), new_y)


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
        # objectName-селектор: фон относится только к этому виджету
        # и не каскадирует в дочерние QComboBox / QLineEdit.
        # Сразу здесь же задаём явные стили полей настроек — раньше
        # они были «прозрачными» на чёрном из-за наследования.
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
                /* Right-padding 24px — чтобы текст combobox'а не лез под
                   chevron, который paintEvent рисует в правой части поля.
                   На QLineEdit (битрейт) лишний паддинг безвреден. */
                padding: 6px 24px 6px 10px;
                font-size: {theme.FONT_SIZE_SM}px;
            }}
            QWidget#settingsBar QComboBox:hover,
            QWidget#settingsBar QLineEdit:hover {{
                /* Bg-tint 0.20 — единый оттенок с calibrate-кнопкой и
                   overlay-кнопками камер (prev/next/back/joy). Раньше
                   тут было 0.10, поля подсвечивались заметно слабее
                   соседних элементов на той же панели. Border при hover
                   не трогаем — это эталон поведения от save-кнопки. */
                background: rgba(42, 130, 218, 0.20);
            }}
            QWidget#settingsBar QComboBox:focus,
            QWidget#settingsBar QLineEdit:focus {{
                border-color: {theme.ACCENT};
            }}
            /* Popup-список разрешения/FPS — единый язык акцента для
               item hover/selected. selection-color/background применяются
               и для клавиатурной навигации стрелками. Фон самого popup'а
               совпадает с background полей (BG_INPUT) — визуально
               воспринимается как «опустившаяся часть» того же поля. */
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
        self.resolution_box = _BoundedComboBox()
        self.resolution_box.setMinimumWidth(140)
        self.resolution_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.resolution_box.currentIndexChanged.connect(self._on_resolution_changed)
        # Курсор-рука на самом поле, и тот же курсор унаследует view списка —
        # на dropdown items это не само QSS-property (Qt не уважает CSS
        # `cursor: pointer` на QAbstractItemView), а setCursor на view.
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
        # Курсор-рука на bitrate-поле для визуальной консистентности с
        # combos рядом. Текст внутри (когда поле в фокусе) рендерится с
        # обычным I-beam курсором — Qt сам переключает.
        self.bitrate_input.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self.bitrate_input)

        # ── Кнопка принудительной калибровки камер ────────────────────────────
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

        # ── Кнопка сохранения ─────────────────────────────────────────────────
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
