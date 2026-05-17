# ═══════════════════════════════════════════════════════════════════════════════
#  DESIGN SYSTEM — единственный файл для всех визуальных настроек
#  Чтобы изменить цвет, шрифт, отступ или размер — редактируй только здесь.
#
#  Палитра выровнена со стилем сайта Mavix (тёмный фон + cyan-акцент).
# ═══════════════════════════════════════════════════════════════════════════════

# ── Цвета ─────────────────────────────────────────────────────────────────────
BG            = "#07090E"   # deep space navy — основной фон окна
BG_SURFACE    = "#11151D"   # панели, шапки, тулбары
BG_INPUT      = "#161B24"   # карточки, поля ввода
BG_HOVER      = "#1A2030"   # фон при наведении
BORDER        = "#1F2733"   # рамка по умолчанию
BORDER_HOVER  = "#2A3340"   # рамка при наведении
BORDER_FOCUS  = "#22d3ee"   # рамка при фокусе — cyan-акцент
ACCENT        = "#22d3ee"   # основной cyan-акцент (Tailwind cyan-400)
ACCENT_HOVER  = "#67e8f9"   # акцент при наведении (светлее)
ACCENT_PRESS  = "#06b6d4"   # акцент при нажатии (темнее)
ACCENT_SUBTLE = "rgba(34, 211, 238, 0.12)"  # лёгкая cyan-подсветка
CYAN          = "#22d3ee"   # синоним ACCENT для существующих ссылок
TEXT_PRIMARY  = "#E8EEF5"   # основной текст
TEXT_MUTED    = "#8893A4"   # вторичный / приглушённый
TEXT_DISABLED = "#4A5563"   # неактивный
BORDER_DARK   = "#0E1117"   # тёмная сетка / разделители (StickWidget)
STATUS_READY  = "#4ADE80"   # зелёный — готов / онлайн
STATUS_ERROR  = "#F87171"   # красный — недоступен / ошибка
STATUS_ARM    = "#4ADE80"   # ARM (полётный экран)
STATUS_DISARM = "#F87171"   # DISARM (полётный экран)
WARNING       = "#FBBF24"   # жёлтое предупреждение
BG_VIDEO      = "#000000"   # фон видеопотока

# ── Шрифты ────────────────────────────────────────────────────────────────────
# Inter — основной интерфейсный, JetBrains Mono — для моноширинных
# (ID дронов, токены). Если Inter не установлен в системе, Qt
# подставит дефолтный sans-serif из цепочки fallback.
FONT_FAMILY      = '"Inter", "Segoe UI", "Helvetica Neue", Arial, sans-serif'
FONT_FAMILY_MONO = '"JetBrains Mono", "SF Mono", "Cascadia Mono", Consolas, monospace'

# ── Отступы (px) ──────────────────────────────────────────────────────────────
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 16
SPACE_LG = 24
SPACE_XL = 40

# ── Скругления углов (px) ─────────────────────────────────────────────────────
RADIUS_SM = 6
RADIUS_MD = 8
RADIUS_LG = 12

# ── Размеры шрифта (px) ───────────────────────────────────────────────────────
FONT_SIZE_SM    = 14
FONT_SIZE_BASE  = 16
FONT_SIZE_LG    = 20
FONT_SIZE_TITLE = 24
FONT_SIZE_HERO  = 32

# ── Размеры кнопок-иконок оверлея (px) ───────────────────────────────────────
OVERLAY_BTN_CORNER      = 60   # назад / джойстик (угловые)
OVERLAY_BTN_CORNER_ICON = 36   # размер SVG-иконки внутри угловой кнопки
OVERLAY_BTN_SIDE        = 64   # стрелки переключения камер (боковые)
OVERLAY_BTN_SIDE_FONT   = 24   # размер символа стрелки в боковой кнопке

# ── Анимации ──────────────────────────────────────────────────────────────────
ANIM_FAST = 150   # мс — короткие переходы (hover)
ANIM_MED  = 200   # мс — focus glow, появление

# ═══════════════════════════════════════════════════════════════════════════════
#  ГЛОБАЛЬНЫЙ STYLESHEET — применяется ко всему приложению через
#  app.setStyleSheet() в __main__.py. Охватывает все стандартные Qt-виджеты.
#  Виджет-специфичные стили ниже могут дополнять или переопределять.
# ═══════════════════════════════════════════════════════════════════════════════

QSS_GLOBAL = f"""

/* ── Базовые элементы ─────────────────────────────────────────────────────── */
QWidget {{
    background-color: {BG};
    color: {TEXT_PRIMARY};
    font-family: {FONT_FAMILY};
    font-size: {FONT_SIZE_BASE}px;
}}

QMainWindow, QDialog {{
    background-color: {BG};
}}

/* ── Кнопки (универсальный стиль, ghost / outline) ────────────────────────── */
QPushButton {{
    background-color: transparent;
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD}px;
    padding: 8px 16px;
    font-size: {FONT_SIZE_SM}px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {BG_HOVER};
    border-color: {BORDER_HOVER};
    color: {TEXT_PRIMARY};
}}
QPushButton:pressed {{
    background-color: {BG_INPUT};
    border-color: {ACCENT_PRESS};
}}
QPushButton:disabled {{
    background-color: transparent;
    color: {TEXT_DISABLED};
    border-color: {BORDER};
}}
QPushButton:checked {{
    background-color: {ACCENT_SUBTLE};
    border-color: {ACCENT};
    color: {ACCENT};
}}

/* ── Поля ввода ────────────────────────────────────────────────────────────── */
QLineEdit {{
    background-color: {BG_INPUT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD}px;
    padding: 9px 12px;
    selection-background-color: {ACCENT};
    selection-color: {BG};
}}
QLineEdit:hover:!focus {{
    border-color: {BORDER_HOVER};
}}
QLineEdit:focus {{
    border-color: {ACCENT};
}}
QLineEdit:disabled {{
    color: {TEXT_DISABLED};
    border-color: {BORDER};
}}

/* ── Выпадающий список ─────────────────────────────────────────────────────── */
QComboBox {{
    background-color: {BG_INPUT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD}px;
    padding: 8px 12px;
    min-width: 80px;
}}
QComboBox:hover {{
    border-color: {BORDER_HOVER};
}}
QComboBox:focus {{
    border-color: {ACCENT};
}}
QComboBox::drop-down {{
    width: 0;
    border: none;
}}
QComboBox::down-arrow {{
    image: none;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_SURFACE};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD}px;
    selection-background-color: {ACCENT_SUBTLE};
    selection-color: {TEXT_PRIMARY};
    outline: none;
    padding: 4px;
}}
QComboBox QAbstractItemView::item {{
    padding: 7px 12px;
    border-radius: {RADIUS_SM}px;
}}
QComboBox QAbstractItemView::item:hover {{
    background-color: {BG_HOVER};
}}

/* ── Списки (QListWidget) ──────────────────────────────────────────────────── */
QListWidget {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD}px;
    outline: none;
    padding: 4px;
}}
QListWidget::item {{
    color: {TEXT_PRIMARY};
    padding: 9px 12px;
    border-radius: {RADIUS_SM}px;
    border: 1px solid transparent;
}}
QListWidget::item:hover {{
    background-color: {BG_HOVER};
}}
QListWidget::item:selected {{
    background-color: {ACCENT_SUBTLE};
    border-color: {ACCENT};
    color: {TEXT_PRIMARY};
}}

/* ── Таблица / дерево ──────────────────────────────────────────────────────── */
QAbstractItemView {{
    background-color: {BG_SURFACE};
    alternate-background-color: {BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT_SUBTLE};
    selection-color: {TEXT_PRIMARY};
    gridline-color: {BORDER};
    outline: none;
}}
QAbstractItemView::item:hover {{
    background-color: {BG_HOVER};
}}

/* ── Чекбоксы и радиокнопки ────────────────────────────────────────────────── */
QCheckBox, QRadioButton {{
    color: {TEXT_PRIMARY};
    spacing: 8px;
    background: transparent;
}}
QCheckBox:hover, QRadioButton:hover {{
    color: {ACCENT_HOVER};
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    background: {BG_INPUT};
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {ACCENT};
    background: {BG_HOVER};
}}
QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}
QRadioButton::indicator {{
    border-radius: 8px;
}}
QRadioButton::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}

/* ── GroupBox ──────────────────────────────────────────────────────────────── */
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD}px;
    margin-top: 14px;
    padding-top: 8px;
    color: {TEXT_MUTED};
    font-size: {FONT_SIZE_SM}px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
}}

/* ── Вкладки ───────────────────────────────────────────────────────────────── */
QTabBar::tab {{
    background: transparent;
    color: {TEXT_MUTED};
    padding: 9px 18px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: {FONT_SIZE_SM}px;
}}
QTabBar::tab:hover {{
    color: {TEXT_PRIMARY};
}}
QTabBar::tab:selected {{
    color: {ACCENT};
    border-bottom-color: {ACCENT};
}}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD}px;
}}

/* ── Скроллбары ────────────────────────────────────────────────────────────── */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    border: none;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {BORDER_HOVER};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    border: none;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER};
    border-radius: 4px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {BORDER_HOVER};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* ── Тултипы ───────────────────────────────────────────────────────────────── */
QToolTip {{
    background-color: {BG_SURFACE};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    padding: 6px 10px;
    border-radius: {RADIUS_SM}px;
    font-size: {FONT_SIZE_SM}px;
}}

/* ── Строка меню / тулбар ──────────────────────────────────────────────────── */
QMenuBar {{
    background: {BG};
    color: {TEXT_PRIMARY};
    border-bottom: 1px solid {BORDER};
}}
QMenuBar::item:hover {{
    background: {ACCENT_SUBTLE};
    color: {TEXT_PRIMARY};
}}
QMenu {{
    background: {BG_SURFACE};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD}px;
    padding: 4px;
}}
QMenu::item {{
    padding: 8px 20px 8px 14px;
    border-radius: {RADIUS_SM}px;
}}
QMenu::item:hover {{
    background: {BG_HOVER};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 4px 8px;
}}

/* ── Слайдер ───────────────────────────────────────────────────────────────── */
QSlider::groove:horizontal {{
    height: 4px;
    background: {BORDER};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {ACCENT};
    border: none;
    width: 14px;
    height: 14px;
    border-radius: 7px;
    margin: -5px 0;
}}
QSlider::handle:horizontal:hover {{
    background: {ACCENT_HOVER};
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 2px;
}}

/* ── Прогресс-бар ──────────────────────────────────────────────────────────── */
QProgressBar {{
    background: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_SM}px;
    text-align: center;
    color: {TEXT_PRIMARY};
    font-size: {FONT_SIZE_SM}px;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: {RADIUS_SM}px;
}}

/* ── Метки (QLabel) — базовый цвет ─────────────────────────────────────────── */
QLabel {{
    color: {TEXT_PRIMARY};
    background: transparent;
}}

"""

# ═══════════════════════════════════════════════════════════════════════════════
#  КОМПОНЕНТНЫЕ СТИЛИ — для конкретных виджетов, переопределяют глобальные
#  правила через widget.setStyleSheet(theme.QSS_*)
# ═══════════════════════════════════════════════════════════════════════════════

# Поле ввода с увеличенным паддингом (токен, поиск)
QSS_INPUT = f"""
QLineEdit {{
    background-color: {BG_INPUT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD}px;
    padding: 11px 14px;
    font-size: {FONT_SIZE_BASE}px;
    selection-background-color: {ACCENT};
    selection-color: {BG};
}}
QLineEdit:hover:!focus {{
    border-color: {BORDER_HOVER};
}}
QLineEdit:focus {{
    border-color: {ACCENT};
}}
"""

# Основная кнопка (cyan-заливка, тёмный текст — как btn-primary на сайте)
QSS_BUTTON_PRIMARY = f"""
QPushButton {{
    background-color: {ACCENT};
    color: {BG};
    border: none;
    border-radius: {RADIUS_MD}px;
    padding: 11px 22px;
    font-size: {FONT_SIZE_BASE}px;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: {ACCENT_HOVER};
    border: none;
}}
QPushButton:pressed {{
    background-color: {ACCENT_PRESS};
}}
QPushButton:disabled {{
    background-color: {BG_HOVER};
    color: {TEXT_DISABLED};
    border: none;
}}
"""

# Вторичная кнопка (ghost / outline) — для шапки кабинета, действий в карточках
QSS_BUTTON_SECONDARY = f"""
QPushButton {{
    background-color: transparent;
    color: {TEXT_MUTED};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD}px;
    padding: 8px 16px;
    font-size: {FONT_SIZE_SM}px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {BG_HOVER};
    border-color: {BORDER_HOVER};
    color: {TEXT_PRIMARY};
}}
QPushButton:pressed {{
    background-color: {BG_INPUT};
    border-color: {ACCENT_PRESS};
}}
"""

# Карточка на экране токена (большая, со скруглёнными краями)
QSS_TOKEN_CARD = f"""
QWidget#tokenCard {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_LG}px;
}}
"""

# Икон-кнопка без рамки и фона — для icon-only кнопок (eye, joystick
# card actions). На hover — лёгкая подложка, на pressed — чуть темнее.
QSS_BUTTON_ICON = f"""
QPushButton {{
    background: transparent;
    border: none;
    border-radius: {RADIUS_MD}px;
    padding: 6px;
}}
QPushButton:hover {{
    background-color: {BG_HOVER};
}}
QPushButton:pressed {{
    background-color: {BG_INPUT};
}}
QPushButton:disabled {{
    background: transparent;
}}
"""
