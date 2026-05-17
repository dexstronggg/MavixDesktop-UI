# ═══════════════════════════════════════════════════════════════════════════════
#  DESIGN SYSTEM — единственный файл для всех визуальных настроек
#  Чтобы изменить цвет, шрифт, отступ или размер — редактируй только здесь.
# ═══════════════════════════════════════════════════════════════════════════════

# ── Цвета ─────────────────────────────────────────────────────────────────────
BG            = "#1e1e1e"   # фон окна / страниц
BG_SURFACE    = "#252525"   # фон карточек / панелей
BG_INPUT      = "#2a2a2a"   # фон полей ввода
BG_HOVER      = "#2e2e2e"   # фон при наведении (универсальный)
BORDER        = "#3a3a3a"   # рамка по умолчанию
BORDER_HOVER  = "#505050"   # рамка при наведении
BORDER_FOCUS  = "#2a82da"   # рамка при фокусе / активном состоянии
ACCENT        = "#2a82da"   # основной голубой акцент
ACCENT_HOVER  = "#3d9ae8"   # акцент при наведении (светлее)
ACCENT_PRESS  = "#1f6ab0"   # акцент при нажатии (темнее)
ACCENT_SUBTLE = "rgba(42, 130, 218, 0.15)"  # очень лёгкая голубая подсветка
CYAN          = "#00D4FF"   # вторичный акцент (виджет джойстика)
TEXT_PRIMARY  = "#ffffff"
TEXT_MUTED    = "#aaaaaa"
TEXT_DISABLED = "#555555"
BORDER_DARK   = "#444444"   # тёмная сетка / разделители (StickWidget)
STATUS_READY  = "#4caf50"   # зелёный — дрон готов / откалиброван
STATUS_ERROR  = "#f44336"   # красный — дрон недоступен / не откалиброван
STATUS_ARM    = "#44ff44"   # ARM (полётный экран)
STATUS_DISARM = "#ff4444"   # DISARM (полётный экран)
WARNING       = "#e8a000"   # предупреждение
BG_VIDEO      = "#000000"   # фон видеопотока

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
FONT_SIZE_SM    = 15
FONT_SIZE_BASE  = 20
FONT_SIZE_LG    = 24
FONT_SIZE_TITLE = 28
FONT_SIZE_HERO  = 34

# ── Размеры кнопок-иконок оверлея (px) ───────────────────────────────────────
OVERLAY_BTN_CORNER      = 60   # назад / джойстик (угловые)
OVERLAY_BTN_CORNER_ICON = 36   # размер SVG-иконки внутри угловой кнопки
OVERLAY_BTN_SIDE        = 64   # стрелки переключения камер (боковые)
OVERLAY_BTN_SIDE_FONT   = 24   # размер символа стрелки в боковой кнопке

# ── Анимации ──────────────────────────────────────────────────────────────────
ANIM_FAST = 150   # мс — короткие переходы (hover)
ANIM_MED  = 200   # мс — focus glow, появление

# ═══════════════════════════════════════════════════════════════════════════════
#  ГЛОБАЛЬНЫЙ STYLESHEET — применяется ко всему приложению через app.setStyleSheet()
#  Охватывает все стандартные Qt-виджеты. Виджет-специфичные стили ниже
#  могут дополнять или переопределять отдельные правила.
# ═══════════════════════════════════════════════════════════════════════════════

QSS_GLOBAL = f"""

/* ── Кнопки (универсальный стиль) ─────────────────────────────────────────── */
QPushButton {{
    background-color: {BG_SURFACE};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD}px;
    padding: 7px 16px;
    font-size: {FONT_SIZE_SM}px;
}}
QPushButton:hover {{
    background-color: {BG_HOVER};
    border-color: {BORDER_FOCUS};
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
    color: {ACCENT_HOVER};
}}

/* ── Поля ввода ────────────────────────────────────────────────────────────── */
QLineEdit {{
    background-color: {BG_INPUT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD}px;
    padding: 8px 12px;
    selection-background-color: {ACCENT};
    selection-color: {TEXT_PRIMARY};
}}
QLineEdit:hover:!focus {{
    border-color: {BORDER_HOVER};
}}
QLineEdit:focus {{
    border-color: {BORDER_FOCUS};
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
    padding: 7px 12px;
    min-width: 80px;
}}
QComboBox:hover {{
    border-color: {BORDER_HOVER};
}}
QComboBox:focus {{
    border-color: {BORDER_FOCUS};
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
    padding: 6px 12px;
    border-radius: {RADIUS_SM}px;
}}
QComboBox QAbstractItemView::item:hover {{
    background-color: {BG_HOVER};
    border: 1px solid {BORDER_FOCUS};
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
    padding: 8px 12px;
    border-radius: {RADIUS_SM}px;
    border: 1px solid transparent;
}}
QListWidget::item:hover {{
    background-color: {BG_HOVER};
    border-color: {BORDER_FOCUS};
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
    border: 1px solid {BORDER_FOCUS};
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
    border-color: {BORDER_FOCUS};
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
    padding: 8px 18px;
    border: none;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:hover {{
    color: {TEXT_PRIMARY};
    border-bottom-color: {BORDER_FOCUS};
    background: {ACCENT_SUBTLE};
}}
QTabBar::tab:selected {{
    color: {TEXT_PRIMARY};
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
    background: {TEXT_DISABLED};
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
    background: {TEXT_DISABLED};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* ── Тултипы ───────────────────────────────────────────────────────────────── */
QToolTip {{
    background-color: {BG_SURFACE};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    padding: 5px 10px;
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
    padding: 7px 20px 7px 12px;
    border-radius: {RADIUS_SM}px;
}}
QMenu::item:hover {{
    background: {BG_HOVER};
    border: 1px solid {BORDER_FOCUS};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 4px 8px;
}}

/* ── QDialog / QMessageBox ─────────────────────────────────────────────────── */
QDialog {{
    background: {BG};
}}
QMessageBox {{
    background: {BG};
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
    padding: 10px 14px;
    font-size: {FONT_SIZE_BASE}px;
    selection-background-color: {ACCENT};
}}
QLineEdit:hover:!focus {{
    border-color: {BORDER_HOVER};
}}
"""

# Основная кнопка (заливка акцентом)
QSS_BUTTON_PRIMARY = f"""
QPushButton {{
    background-color: {ACCENT};
    color: {TEXT_PRIMARY};
    border: none;
    border-radius: {RADIUS_MD}px;
    padding: 10px 20px;
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
    background-color: #333;
    color: {TEXT_DISABLED};
    border: none;
}}
"""

# Вторичная кнопка (ghost / outline)
QSS_BUTTON_SECONDARY = f"""
QPushButton {{
    background-color: transparent;
    color: {TEXT_MUTED};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD}px;
    padding: 6px 14px;
    font-size: {FONT_SIZE_SM}px;
}}
QPushButton:hover {{
    background-color: {BG_HOVER};
    border-color: {BORDER_FOCUS};
    color: {TEXT_PRIMARY};
}}
QPushButton:pressed {{
    background-color: {BG_INPUT};
    border-color: {ACCENT_PRESS};
}}
"""

# Карточка на экране токена
QSS_TOKEN_CARD = f"""
QWidget#tokenCard {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_LG}px;
}}
"""
