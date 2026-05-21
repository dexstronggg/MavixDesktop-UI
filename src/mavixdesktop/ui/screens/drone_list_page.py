from typing import Callable

from PySide6.QtCore import Qt, Signal, QTimer, QUrl
from PySide6.QtGui import QPixmap, QPainter, QIcon, QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame,
)

from mavixdesktop.core.config import settings
from mavixdesktop.ui.style import theme
from .utils import svg_pixmap, mavix_logo_pixmap, AnimatedCard, CardGrid


def _brand_widget(parent: QWidget | None = None) -> QWidget:
    """Логотип-бренд: квадратик с M + надпись MAVIX, как в шапке сайта."""
    w = QWidget(parent)
    w.setStyleSheet('background: transparent;')
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(10)
    logo = QLabel()
    logo.setFixedSize(28, 28)
    logo.setPixmap(mavix_logo_pixmap(28))
    logo.setStyleSheet('background: transparent;')
    h.addWidget(logo)
    wordmark = QLabel('MAVIX')
    wordmark.setStyleSheet(
        f'background: transparent; color: {theme.TEXT_PRIMARY};'
        f'font-family: {theme.FONT_FAMILY_MONO}; font-weight: 600;'
        f'font-size: {theme.FONT_SIZE_BASE}px; letter-spacing: 2px;'
    )
    h.addWidget(wordmark)
    return w


def _icon_button(icon_name: str | None, text: str,
                 parent: QWidget | None = None) -> QPushButton:
    """Ghost-кнопка с опциональной SVG-иконкой + текстом.

    Если ``icon_name`` is None — кнопка только текстовая (используется
    для «Выйти», чтобы не делать акцент иконкой).
    """
    btn = QPushButton(text, parent)
    if icon_name is not None:
        btn.setIcon(QIcon(svg_pixmap(icon_name, 16, color=theme.TEXT_PRIMARY)))
    btn.setCursor(Qt.PointingHandCursor)
    btn.setStyleSheet(theme.QSS_BUTTON_SECONDARY)
    btn.setMinimumHeight(36)
    return btn

_CARD_W   = 210
_CARD_H   = 230
_ICON_SIZE = 88
_ID_MAX_CHARS = 16  # сколько символов drone_id влезает в карточку 210px


# Цвета hover-полосы и статус-точки по статусу. Используется и в карточке,
# и в stats-row выше грида — единый источник правды.
_STATUS_COLORS = {
    'ready':      theme.STATUS_READY,    # зелёный
    'offline':    theme.STATUS_ERROR,    # красный
    'connecting': theme.WARNING,         # жёлтый
}
_STATUS_LABELS = {
    'ready':      'готов',
    'offline':    'offline',
    'connecting': 'подключение',
}


def _dim_pixmap(src: QPixmap, opacity: float = 0.3) -> QPixmap:
    result = QPixmap(src.size())
    result.fill(Qt.transparent)
    p = QPainter(result)
    p.setOpacity(opacity)
    p.drawPixmap(0, 0, src)
    p.end()
    return result


def _truncate_id(drone_id: str, max_chars: int = _ID_MAX_CHARS) -> str:
    """Middle-ellipsis для длинных drone_id.

    Раньше тут было ``id[:6]`` — для ``demo-online-0001`` это давало
    ``demo-o`` и операторы не могли отличить дроны. Теперь видна и
    голова, и хвост: ``demo-online-0001`` → ``demo-online-0001`` (16 → 16);
    ``e3a7...9f01`` для совсем длинных hash-id (64 hex). Полный id
    остаётся в tooltip — копируется хоть и не через карточку, но
    хотя бы видно при наведении.
    """
    if not drone_id:
        return '——'
    if len(drone_id) <= max_chars:
        return drone_id
    head = (max_chars - 3) // 2
    tail = max_chars - 3 - head
    return f'{drone_id[:head]}…{drone_id[-tail:]}'


class DroneCard(AnimatedCard):
    clicked = Signal(str)

    def __init__(self, drone_id: str, status: str, index: int, icon_pixmap: QPixmap):
        super().__init__()
        self._drone_id = drone_id
        self._status = status
        self._ready = (status == 'ready')
        # Hover-полоса AnimatedCard перекрашивается под статус —
        # ready=зелёная, offline=красная, connecting=жёлтая. На занятом
        # экране оператор по цвету полосы под курсором сразу видит,
        # с каким дроном он взаимодействует.
        self._bar_color = _STATUS_COLORS.get(status, theme.ACCENT)

        self.setFixedSize(_CARD_W, _CARD_H)
        if self._ready:
            self.setCursor(Qt.PointingHandCursor)

        # Border у hover тоже окрашивается по статусу — единый цветовой
        # язык со status-точкой и hover-полосой.
        hover_border = self._bar_color
        self._style_normal = f"""
            QWidget#droneCard {{
                background: {theme.BG_INPUT};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS_LG}px;
            }}
        """
        self._style_hover = f"""
            QWidget#droneCard {{
                background: {theme.BG_HOVER};
                border: 1px solid {hover_border};
                border-radius: {theme.RADIUS_LG}px;
            }}
        """
        self.setObjectName('droneCard')
        self.setStyleSheet(self._style_normal)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(6)
        layout.setContentsMargins(12, 18, 12, 14)

        icon_lbl = QLabel()
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setPixmap(icon_pixmap if self._ready else _dim_pixmap(icon_pixmap))
        icon_lbl.setStyleSheet('background: transparent; border: none;')

        name_lbl = QLabel(f'Дрон №{index + 1}')
        name_lbl.setAlignment(Qt.AlignCenter)
        name_lbl.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY if self._ready else theme.TEXT_DISABLED};'
            f'font-size: {theme.FONT_SIZE_SM}px; font-weight: 600;'
            'background: transparent; border: none;'
        )

        id_lbl = QLabel(_truncate_id(drone_id))
        id_lbl.setAlignment(Qt.AlignCenter)
        id_lbl.setStyleSheet(
            f'color: {theme.TEXT_MUTED if self._ready else theme.TEXT_DISABLED};'
            f'font-size: {theme.FONT_SIZE_SM - 1}px;'
            f'font-family: {theme.FONT_FAMILY_MONO};'
            'background: transparent; border: none;'
        )

        # Status chip — пилюля с фоном цвета статуса, заметнее чем dot+text.
        status_chip = QLabel(_STATUS_LABELS.get(status, status))
        status_chip.setAlignment(Qt.AlignCenter)
        chip_color = _STATUS_COLORS.get(status, theme.TEXT_MUTED)
        # rgba-фон через прямое декомпозицию hex — QColor.fromString дала
        # бы то же, но f-string проще читать.
        chip_rgba = self._hex_to_rgba(chip_color, 0.14)
        status_chip.setStyleSheet(
            f'color: {chip_color}; background: {chip_rgba};'
            f'border: 1px solid {self._hex_to_rgba(chip_color, 0.30)};'
            f'border-radius: 10px; padding: 3px 12px;'
            f'font-size: {theme.FONT_SIZE_SM - 2}px; font-weight: 500;'
        )
        status_chip.setMinimumHeight(22)

        status_wrap = QWidget()
        status_wrap.setStyleSheet('background: transparent; border: none;')
        sw = QHBoxLayout(status_wrap)
        sw.setAlignment(Qt.AlignCenter)
        sw.setContentsMargins(0, 0, 0, 0)
        sw.addWidget(status_chip)

        layout.addWidget(icon_lbl)
        layout.addWidget(name_lbl)
        layout.addWidget(id_lbl)
        layout.addWidget(status_wrap)

    @staticmethod
    def _hex_to_rgba(hex_color: str, alpha: float) -> str:
        h = hex_color.lstrip('#')
        if len(h) != 6:
            return hex_color
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
        return f'rgba({r},{g},{b},{alpha})'

    def _on_hover(self, hovered: bool):
        effective = hovered and self._ready
        self.setStyleSheet(self._style_hover if effective else self._style_normal)
        self._animate_bar(1000 if effective else 0)

    def mousePressEvent(self, event):
        if self._ready and event.button() == Qt.LeftButton:
            self.clicked.emit(self._drone_id)
        super().mousePressEvent(event)


class _DroneGrid(CardGrid):
    CARD_W = _CARD_W
    CARD_H = _CARD_H
    GAP    = 20


class _StatsBar(QWidget):
    """Сводка по флоту: всего / готов / offline / подключение.

    Обновляется из ``DroneListPage.update``; пустой грид/неизвестные
    статусы корректно дают нули. Визуально — горизонтальный ряд
    «{число} {подпись}», с тонкими разделителями между пунктами.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName('statsBar')
        self.setFixedHeight(56)
        self.setStyleSheet(f"""
            QWidget#statsBar {{
                background: transparent;
                border-bottom: 1px solid {theme.BORDER};
            }}
        """)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(28, 0, 28, 0)
        lay.setSpacing(0)

        self._items: dict[str, tuple[QLabel, QLabel]] = {}
        for key, label, color in [
            ('total',      'всего',       theme.TEXT_PRIMARY),
            ('ready',      'готов',       _STATUS_COLORS['ready']),
            ('offline',    'offline',     _STATUS_COLORS['offline']),
            ('connecting', 'подключение', _STATUS_COLORS['connecting']),
        ]:
            block = self._build_item(label, color)
            lay.addWidget(block)
            if key != 'connecting':
                sep = QFrame()
                sep.setFixedSize(1, 22)
                sep.setStyleSheet(f'background: {theme.BORDER}; border: none;')
                lay.addSpacing(20)
                lay.addWidget(sep)
                lay.addSpacing(20)
        lay.addStretch()

    def _build_item(self, label_text: str, color: str) -> QWidget:
        wrap = QWidget()
        wrap.setStyleSheet('background: transparent;')
        h = QHBoxLayout(wrap)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        value = QLabel('0')
        value.setStyleSheet(
            f'color: {color}; background: transparent; border: none;'
            f'font-size: {theme.FONT_SIZE_LG}px; font-weight: 700;'
            f'font-family: {theme.FONT_FAMILY_MONO};'
        )

        caption = QLabel(label_text)
        caption.setStyleSheet(
            f'color: {theme.TEXT_MUTED}; background: transparent; border: none;'
            f'font-size: {theme.FONT_SIZE_SM}px;'
        )

        h.addWidget(value)
        h.addWidget(caption)
        self._items[label_text] = (value, caption)
        return wrap

    def set_counts(self, total: int, ready: int, offline: int, connecting: int) -> None:
        for label, count in [
            ('всего', total),
            ('готов', ready),
            ('offline', offline),
            ('подключение', connecting),
        ]:
            self._items[label][0].setText(str(count))


class _DocsHint(QWidget):
    """Подсказка-«подвал» внизу drone-list: книжная иконка + текст
    «Не видите свой дрон?» + строка про документацию.

    Заполняет пустое пространство страницы когда дронов мало (3 карточки
    в 1080p окне оставляли >700px пустоты под собой). Всегда виден,
    при большом количестве дронов ScrollArea сверху занимает высоту,
    hint остаётся на дне как нативный footer.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName('docsHint')
        self.setFixedHeight(72)
        self.setStyleSheet(f"""
            QWidget#docsHint {{
                background: {theme.BG_SURFACE};
                border-top: 1px solid {theme.BORDER};
            }}
            QWidget#docsHint QLabel {{
                background: transparent;
            }}
        """)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(28, 0, 28, 0)
        lay.setSpacing(14)
        lay.addStretch()

        # Иконка дрона в muted-цвете — тот же визуальный язык что у
        # карточек выше, но без акцента (это пассивная подсказка).
        icon = QLabel()
        icon.setFixedSize(24, 24)
        icon.setPixmap(svg_pixmap('drone_list.svg', 24, color=theme.TEXT_MUTED))
        lay.addWidget(icon)

        title = QLabel('Не видите свой дрон?')
        title.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; font-size: {theme.FONT_SIZE_SM}px;'
            'font-weight: 600;'
        )
        lay.addWidget(title)

        sep = QLabel('·')
        sep.setStyleSheet(f'color: {theme.TEXT_DISABLED}; font-size: {theme.FONT_SIZE_BASE}px;')
        lay.addWidget(sep)

        # Кликабельная ссылка на документацию ЛК. settings.http_url —
        # базовый URL сервера из конфига MavixDesktop (по дефолту
        # http://localhost:8000, на проде — публичный домен Mavix);
        # роут /dashboard/docs/user живёт на MavixWeb, который обычно
        # развёрнут на том же хосте за reverse-proxy.
        link = QLabel('Как зарегистрировать дрон — см. документацию')
        link.setCursor(Qt.PointingHandCursor)
        link.setStyleSheet(
            f'color: {theme.ACCENT}; font-size: {theme.FONT_SIZE_SM}px;'
            f'text-decoration: underline;'
        )
        link.mousePressEvent = self._open_docs
        lay.addWidget(link)

        lay.addStretch()

    def _open_docs(self, _event) -> None:
        base = settings.http_url.rstrip('/')
        QDesktopServices.openUrl(QUrl(f'{base}/dashboard/docs/user'))


class DroneListPage(QWidget):
    def __init__(self, on_select: Callable, on_refresh: Callable,
                 on_logout: Callable, on_joystick_cfg: Callable):
        super().__init__()
        self._on_select = on_select
        self._icon = svg_pixmap('drone_list.svg', _ICON_SIZE, color=theme.ACCENT)

        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        top_bar = QWidget()
        # #objectName-селектор: фон не каскадирует в дочерние виджеты.
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

        # Лево: лого-бренд + заголовок раздела.
        tb.addWidget(_brand_widget(top_bar))
        sep = QFrame()
        sep.setFixedSize(1, 22)
        sep.setStyleSheet(f'background: {theme.BORDER}; border: none;')
        tb.addSpacing(8)
        tb.addWidget(sep)
        tb.addSpacing(8)

        title = QLabel('Доступные дроны')
        title.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; font-size: {theme.FONT_SIZE_LG}px;'
            f'font-weight: 600; background: transparent; border: none;'
            f'font-family: {theme.FONT_FAMILY};'
        )
        tb.addWidget(title)
        tb.addStretch()

        # Право: действия.
        joy_btn = _icon_button('joystick.svg', 'Джойстик', top_bar)
        joy_btn.clicked.connect(on_joystick_cfg)

        # «Выйти» — без иконки: символ logout оптически мог читаться
        # как G→. Текста достаточно. Hover красный — действие
        # деструктивное (сброс сессии), а не нейтрально-навигационное
        # как у соседних ghost-кнопок (joy / back).
        logout_btn = _icon_button(None, 'Выйти', top_bar)
        logout_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {theme.TEXT_MUTED};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS_MD}px;
                padding: 8px 16px;
                font-size: {theme.FONT_SIZE_SM}px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: rgba(248, 113, 113, 0.12);
                color: {theme.STATUS_ERROR};
            }}
            QPushButton:pressed {{
                background-color: rgba(248, 113, 113, 0.20);
                color: {theme.STATUS_ERROR};
            }}
        """)
        logout_btn.clicked.connect(on_logout)

        tb.addWidget(joy_btn)
        tb.addWidget(logout_btn)

        self._stats = _StatsBar()
        self._grid = _DroneGrid()
        self._hint = _DocsHint()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(5000)
        self._refresh_timer.timeout.connect(on_refresh)

        scroll = QScrollArea()
        scroll.setWidget(self._grid)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._empty = QLabel('Дроны не найдены\n\nПодождите, список обновляется автоматически')
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setStyleSheet(
            f'color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE_BASE}px;'
        )
        self._empty.hide()

        root.addWidget(top_bar)
        root.addWidget(self._stats)
        root.addWidget(scroll, 1)
        root.addWidget(self._empty, 1)
        # Hint-блок снизу страницы — единый «подвал» с подсказкой как
        # добавить дрон. Всегда виден; при заполненном гриде ScrollArea
        # выше занимает основную высоту, hint остаётся на дне окна.
        root.addWidget(self._hint)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._refresh_timer.stop()

    def update(self, drones: list):
        if not drones:
            self._stats.set_counts(0, 0, 0, 0)
            self._empty.show()
            self._grid.hide()
            self._grid.set_cards([])
            return

        self._empty.hide()
        self._grid.show()

        cards = []
        counts = {'ready': 0, 'offline': 0, 'connecting': 0}
        for i, d in enumerate(drones):
            # Accept both new format ({drone_id, online}) and legacy
            # ({session_id, status}); prefer the new fields when present.
            drone_id = d.get('drone_id', d.get('session_id', ''))
            if 'online' in d:
                status = 'ready' if d.get('online') else 'offline'
            else:
                status = d.get('status', 'unknown')
            if status in counts:
                counts[status] += 1
            card = DroneCard(drone_id, status, i, self._icon)
            card.clicked.connect(self._on_select)
            cards.append(card)

        self._stats.set_counts(
            total=len(drones),
            ready=counts['ready'],
            offline=counts['offline'],
            connecting=counts['connecting'],
        )
        self._grid.set_cards(cards)
