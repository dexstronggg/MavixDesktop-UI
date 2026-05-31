"""UI настроек — редактирование ~/.config/mavixdesktop/config.json из приложения.

Доступно через иконку-шестерёнку на странице логина и на странице списка
дронов. Сохранение пишет JSON-файл и обновляет in-memory singleton
settings (без перезапуска приложения); изменения SIGNAL_URL вступают в
силу при следующем reconnect или логине.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mavixdesktop.core import config as config_module
from mavixdesktop.core import user_config
from mavixdesktop.core.config import settings
from mavixdesktop.ui.screens.utils import svg_pixmap
from mavixdesktop.ui.style import theme

# Значения по умолчанию, подставляемые при «Сбросить к дефолтам». Они
# повторяют dev .env-example, чтобы «чистый» конфиг совпадал с тем, что
# разработчик получает из коробки.
_DEFAULTS = {
    'signal_url': 'http://localhost:8000',
    'stun_server': '',
    'turn_server': '',
    'turn_username': '',
    'turn_password': '',
    'qgc_host': '127.0.0.1',
    'qgc_port': '14550',
    'force_relay': False,
}


class SettingsPage(QWidget):
    """Одностраничная форма.

    on_close вызывается, когда пользователь нажимает «Закрыть» (или
    успешно сохраняет) — host должен вернуть тот экран, что был показан
    до этого.
    """

    def __init__(self, on_close: Callable[[], None]) -> None:
        super().__init__()
        self._on_close = on_close
        self._inputs: dict[str, QLineEdit] = {}
        self._force_relay_cb: QCheckBox | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.SPACE_LG, theme.SPACE_LG, theme.SPACE_LG, theme.SPACE_LG)
        outer.setSpacing(theme.SPACE_MD)

        outer.addWidget(self._build_header())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet('QScrollArea { background: transparent; border: none; }')

        body = QWidget()
        body.setStyleSheet('background: transparent;')
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(theme.SPACE_LG)

        body_layout.addWidget(self._build_card(
            'Сервер',
            'URL базового HTTP-эндпойнта MavixServer. WebSocket-адрес'
            ' выводится из этого значения автоматически.',
            [('signal_url', 'SIGNAL_URL', 'http://example.com:8000')],
        ))

        body_layout.addWidget(self._build_card(
            'WebRTC (STUN/TURN)',
            'Оставьте пустыми, чтобы использовать настройки сервера'
            ' (получаются через /api/v1/ice-servers). Заполните, чтобы'
            ' принудительно использовать свои.',
            [
                ('stun_server',   'STUN сервер',  'stun:host:3478'),
                ('turn_server',   'TURN сервер',  'turn:host:3478'),
                ('turn_username', 'TURN логин',   ''),
                ('turn_password', 'TURN пароль',  ''),
            ],
        ))

        body_layout.addWidget(self._build_card(
            'QGroundControl / MAVLink relay',
            'UDP-сокет, куда desktop форвардит MAVLink-пакеты от дрона'
            ' для QGC. Меняйте только если QGC слушает не на 127.0.0.1:14550.',
            [
                ('qgc_host', 'QGC хост', '127.0.0.1'),
                ('qgc_port', 'QGC порт', '14550'),
            ],
        ))

        body_layout.addWidget(self._build_force_relay_card())

        body_layout.addStretch()

        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        outer.addLayout(self._build_actions())

        self._load_values()

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setStyleSheet('background: transparent;')
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_SM)

        icon = QLabel()
        icon.setPixmap(svg_pixmap('tune.svg', 32, color=theme.ACCENT))

        title = QLabel('Настройки')
        title.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY}; font-size: 24px; font-weight: 700;'
        )

        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addStretch()
        return header

    def _build_card(self, title: str, subtitle: str, fields: list[tuple[str, str, str]]) -> QWidget:
        card = QWidget()
        card.setObjectName('settingsCard')
        card.setStyleSheet(
            f'QWidget#settingsCard {{'
            f' background-color: {theme.BG_INPUT};'
            f' border: 1px solid {theme.BORDER};'
            f' border-radius: {theme.RADIUS_LG}px;'
            f' }}'
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SPACE_LG, theme.SPACE_MD, theme.SPACE_LG, theme.SPACE_MD)
        layout.setSpacing(theme.SPACE_SM)

        h = QLabel(title)
        h.setStyleSheet(f'color: {theme.TEXT_PRIMARY}; font-size: 16px; font-weight: 600;')
        layout.addWidget(h)

        sub = QLabel(subtitle)
        sub.setStyleSheet(f'color: {theme.TEXT_MUTED}; font-size: 13px;')
        sub.setWordWrap(True)
        layout.addWidget(sub)
        layout.addSpacing(theme.SPACE_SM)

        for key, label_text, placeholder in fields:
            row = QVBoxLayout()
            row.setSpacing(4)

            lbl = QLabel(label_text)
            lbl.setStyleSheet(f'color: {theme.TEXT_MUTED}; font-size: 12px; font-weight: 500;')
            row.addWidget(lbl)

            inp = QLineEdit()
            inp.setStyleSheet(theme.QSS_INPUT)
            inp.setPlaceholderText(placeholder)
            inp.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            row.addWidget(inp)

            self._inputs[key] = inp
            layout.addLayout(row)

        return card

    def _build_force_relay_card(self) -> QWidget:
        card = QWidget()
        card.setObjectName('settingsCard')
        card.setStyleSheet(
            f'QWidget#settingsCard {{'
            f' background-color: {theme.BG_INPUT};'
            f' border: 1px solid {theme.BORDER};'
            f' border-radius: {theme.RADIUS_LG}px;'
            f' }}'
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SPACE_LG, theme.SPACE_MD, theme.SPACE_LG, theme.SPACE_MD)
        layout.setSpacing(theme.SPACE_SM)

        h = QLabel('Debug: force-relay (TURN-only)')
        h.setStyleSheet(f'color: {theme.TEXT_PRIMARY}; font-size: 16px; font-weight: 600;')
        layout.addWidget(h)

        sub = QLabel(
            'Имитирует корпоративный/университетский firewall: при включении '
            'все candidate-кандидаты типа host и srflx отбрасываются, '
            'остаются только relay через TURN-сервер. Полезно чтобы '
            'воспроизвести «не подключается из универа» из домашней сети.'
        )
        sub.setStyleSheet(f'color: {theme.TEXT_MUTED}; font-size: 13px;')
        sub.setWordWrap(True)
        layout.addWidget(sub)

        cb = QCheckBox('Включить force-relay режим')
        cb.setStyleSheet(f'color: {theme.TEXT_PRIMARY}; font-size: 13px; padding-top: 4px;')
        self._force_relay_cb = cb
        layout.addWidget(cb)

        return card

    def _build_actions(self) -> QHBoxLayout:
        actions = QHBoxLayout()
        actions.setSpacing(theme.SPACE_SM)

        reset_btn = QPushButton('Сбросить к дефолтам')
        reset_btn.setStyleSheet(theme.QSS_BUTTON_SECONDARY)
        reset_btn.clicked.connect(self._on_reset)

        close_btn = QPushButton('Закрыть')
        close_btn.setStyleSheet(theme.QSS_BUTTON_SECONDARY)
        close_btn.clicked.connect(self._on_close)

        save_btn = QPushButton('Сохранить')
        save_btn.setStyleSheet(theme.QSS_BUTTON_PRIMARY)
        save_btn.clicked.connect(self._on_save)

        actions.addWidget(reset_btn)
        actions.addStretch()
        actions.addWidget(close_btn)
        actions.addWidget(save_btn)
        return actions

    # --- Данные ---

    def _load_values(self) -> None:
        # Берём значения из живого объекта settings, чтобы форма отражала
        # эффективный конфиг (включая возможный override из OS env).
        current = {
            'signal_url': settings.signal_url,
            'stun_server': settings.stun_server,
            'turn_server': settings.turn_server,
            'turn_username': settings.turn_username,
            'turn_password': settings.turn_password,
            'qgc_host': settings.qgc_host,
            'qgc_port': str(settings.qgc_port),
        }
        for key, inp in self._inputs.items():
            inp.setText(current.get(key, ''))
        if self._force_relay_cb is not None:
            self._force_relay_cb.setChecked(bool(getattr(settings, 'force_relay', False)))

    def _collect(self) -> dict:
        values: dict = {key: inp.text().strip() for key, inp in self._inputs.items()}
        if self._force_relay_cb is not None:
            values['force_relay'] = self._force_relay_cb.isChecked()
        return values

    def _on_reset(self) -> None:
        confirm = QMessageBox(self)
        confirm.setWindowTitle('Сбросить настройки?')
        confirm.setText(
            'Все поля будут заполнены значениями по умолчанию.\n'
            'Нажмите «Сохранить», чтобы применить.'
        )
        confirm.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        confirm.setDefaultButton(QMessageBox.Cancel)
        if confirm.exec() != QMessageBox.Ok:
            return
        for key, inp in self._inputs.items():
            inp.setText(_DEFAULTS.get(key, ''))
        if self._force_relay_cb is not None:
            self._force_relay_cb.setChecked(bool(_DEFAULTS.get('force_relay', False)))

    def _on_save(self) -> None:
        values = self._collect()

        # Минимальная валидация: SIGNAL_URL обязателен и должен быть http(s).
        signal_url = values.get('signal_url', '').rstrip('/')
        if not signal_url:
            self._show_error('Поле SIGNAL_URL не может быть пустым.')
            return
        if not (signal_url.startswith('http://') or signal_url.startswith('https://')):
            self._show_error('SIGNAL_URL должен начинаться с http:// или https://')
            return
        values['signal_url'] = signal_url

        # qgc_port должен быть числом.
        port_str = values.get('qgc_port', '14550')
        try:
            port = int(port_str)
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            self._show_error('QGC порт должен быть числом от 1 до 65535.')
            return
        values['qgc_port'] = port

        # Сохраняем JSON, поверх уже существующих ключей (на случай, если
        # там есть что-то, чего UI не знает).
        existing = user_config.load()
        existing.update(values)
        try:
            user_config.save(existing)
        except OSError as exc:
            self._show_error(f'Не удалось сохранить настройки: {exc}')
            return

        config_module.reload_from_user_config()
        self._on_close()

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, 'Ошибка', message)
