"""Settings UI — edits ~/.config/mavixdesktop/config.json from the app."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
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
    QSlider,
    QVBoxLayout,
    QWidget,
)

from mavixdesktop.core import config as config_module
from mavixdesktop.core import user_config
from mavixdesktop.core.config import DEFAULT_SIGNAL_URL, settings
from mavixdesktop.ui.screens.utils import svg_pixmap
from mavixdesktop.ui.style import theme

_DEFAULTS: dict[str, Any] = {
    'signal_url': DEFAULT_SIGNAL_URL,
    'stun_server': '',
    'turn_server': '',
    'turn_username': '',
    'turn_password': '',
    'qgc_host': '127.0.0.1',
    'qgc_port': '14550',
    'force_relay': False,
    'ui_scale': user_config.UI_SCALE_DEFAULT,
}


class SettingsPage(QWidget):
    def __init__(self, on_close: Callable[[], None]) -> None:
        super().__init__()
        self._on_close = on_close
        self._inputs: dict[str, QLineEdit] = {}
        self._force_relay_cb: QCheckBox | None = None
        self._ui_scale_slider: QSlider | None = None
        self._ui_scale_value: QLabel | None = None
        self._ui_scale_saved: int = user_config.load_ui_scale()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.SPACE_LG, theme.SPACE_LG, theme.SPACE_LG, theme.SPACE_LG)
        outer.setSpacing(theme.SPACE_MD)

        outer.addWidget(self._build_header())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
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

        body_layout.addWidget(self._build_ui_scale_card())

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
            inp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            row.addWidget(inp)

            self._inputs[key] = inp
            layout.addLayout(row)

        return card

    def _build_ui_scale_card(self) -> QWidget:
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

        h = QLabel('Масштаб интерфейса')
        h.setStyleSheet(f'color: {theme.TEXT_PRIMARY}; font-size: 16px; font-weight: 600;')
        layout.addWidget(h)

        sub = QLabel(
            'Увеличивает или уменьшает всё сразу: текст, кнопки, отступы, иконки. '
            'Значение умножается на масштаб, заданный в системе, — если там уже '
            'стоит 125%, то 120% здесь дадут итоговые 150%.'
        )
        sub.setStyleSheet(f'color: {theme.TEXT_MUTED}; font-size: 13px;')
        sub.setWordWrap(True)
        layout.addWidget(sub)
        layout.addSpacing(theme.SPACE_SM)

        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_MD)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setMinimum(user_config.UI_SCALE_MIN)
        slider.setMaximum(user_config.UI_SCALE_MAX)
        slider.setSingleStep(user_config.UI_SCALE_STEP)
        slider.setPageStep(user_config.UI_SCALE_STEP * 2)
        slider.setTickInterval(user_config.UI_SCALE_STEP * 2)
        slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        slider.setStyleSheet(theme.QSS_SLIDER)
        slider.setCursor(Qt.CursorShape.PointingHandCursor)
        slider.valueChanged.connect(self._on_ui_scale_changed)
        self._ui_scale_slider = slider

        value_label = QLabel(f'{user_config.UI_SCALE_DEFAULT} %')
        value_label.setMinimumWidth(56)
        value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        value_label.setStyleSheet(
            f'color: {theme.ACCENT}; font-size: 15px; font-weight: 600;'
            f' font-family: {theme.FONT_FAMILY_MONO};'
        )
        self._ui_scale_value = value_label

        row.addWidget(slider, 1)
        row.addWidget(value_label)
        layout.addLayout(row)

        warn = QLabel(
            '⚠  Новый масштаб применится только после полного перезапуска '
            'приложения — закройте его и откройте снова.'
        )
        warn.setStyleSheet(f'color: {theme.WARNING}; font-size: 13px; font-weight: 500;')
        warn.setWordWrap(True)
        layout.addWidget(warn)

        return card

    def _on_ui_scale_changed(self, value: int) -> None:
        step = user_config.UI_SCALE_STEP
        snapped = round(value / step) * step
        if snapped != value and self._ui_scale_slider is not None:
            self._ui_scale_slider.setValue(snapped)
            return
        if self._ui_scale_value is not None:
            self._ui_scale_value.setText(f'{snapped} %')

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

    def _load_values(self) -> None:
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
        self._ui_scale_saved = user_config.load_ui_scale()
        if self._ui_scale_slider is not None:
            self._ui_scale_slider.setValue(self._ui_scale_saved)
        if self._ui_scale_value is not None:
            self._ui_scale_value.setText(f'{self._ui_scale_saved} %')

    def _collect(self) -> dict[str, Any]:
        values: dict[str, Any] = {key: inp.text().strip() for key, inp in self._inputs.items()}
        if self._force_relay_cb is not None:
            values['force_relay'] = self._force_relay_cb.isChecked()
        if self._ui_scale_slider is not None:
            values[user_config.UI_SCALE_KEY] = self._ui_scale_slider.value()
        return values

    def _on_reset(self) -> None:
        confirm = QMessageBox(self)
        confirm.setWindowTitle('Сбросить настройки?')
        confirm.setText(
            'Все поля будут заполнены значениями по умолчанию.\n'
            'Нажмите «Сохранить», чтобы применить.'
        )
        confirm.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        confirm.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if confirm.exec() != QMessageBox.StandardButton.Ok:
            return
        for key, inp in self._inputs.items():
            inp.setText(_DEFAULTS.get(key, ''))
        if self._force_relay_cb is not None:
            self._force_relay_cb.setChecked(bool(_DEFAULTS.get('force_relay', False)))
        if self._ui_scale_slider is not None:
            self._ui_scale_slider.setValue(int(_DEFAULTS['ui_scale']))

    def _on_save(self) -> None:
        values = self._collect()

        signal_url = values.get('signal_url', '').rstrip('/')
        if not signal_url:
            self._show_error('Поле SIGNAL_URL не может быть пустым.')
            return
        if not (signal_url.startswith('http://') or signal_url.startswith('https://')):
            self._show_error('SIGNAL_URL должен начинаться с http:// или https://')
            return
        values['signal_url'] = signal_url

        port_str = values.get('qgc_port', '14550')
        try:
            port = int(port_str)
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            self._show_error('QGC порт должен быть числом от 1 до 65535.')
            return
        values['qgc_port'] = port

        existing = user_config.load()
        existing.update(values)
        try:
            user_config.save(existing)
        except OSError as exc:
            self._show_error(f'Не удалось сохранить настройки: {exc}')
            return

        config_module.reload_from_user_config()

        new_scale = int(values.get(user_config.UI_SCALE_KEY, self._ui_scale_saved))
        if new_scale != self._ui_scale_saved:
            self._ui_scale_saved = new_scale
            self._show_restart_required(new_scale)

        self._on_close()

    def _show_restart_required(self, scale: int) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle('Требуется перезапуск')
        box.setText(f'Масштаб интерфейса сохранён: {scale} %.')
        box.setInformativeText(
            'Он применится только после полного перезапуска приложения.\n'
            'Закройте Mavix и запустите снова.'
        )
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, 'Ошибка', message)
