"""Чтение калиброванных позиций стиков и состояния ARM из pygame Joystick."""
from __future__ import annotations

from collections.abc import Iterable


class JoystickInput:
    """Оборачивает pygame Joystick словарём калибровки.

    Словарь той же формы, что выдаёт calibration.save():
      axis_thr / axis_yaw / axis_pitch / axis_roll → индекс оси для каждого стика
      <name>_min / _max / _center → границы нормализации
      arm_type ('axis' | 'button'), arm_axis_index / arm_button_index
    """

    AXES: Iterable[str] = ('thr', 'yaw', 'pitch', 'roll')

    def __init__(self, joystick_index: int, calibration: dict, pump_events: bool = True) -> None:
        import pygame
        pygame.joystick.init()
        self._joystick_index = joystick_index
        self._js = pygame.joystick.Joystick(joystick_index)
        self._js.init()
        self._cal = calibration
        self._pump_events = pump_events
        self._arm = False
        self._arm_btn_prev = 0
        # Защита от «вошёл в полёт с тумблером в ARM»: пока с момента создания
        # input не увидели DISARM хотя бы раз, is_armed() возвращает False,
        # чтобы вход в полёт не приводил к мгновенному армированию. После
        # первого DISARM — обычная логика (DISARM→ARM работает как всегда).
        self._disarm_seen = False
        # Запоминаем instance_id, чтобы сопоставлять событие device-removed
        # именно с этим joystick (если у пользователя подключено больше
        # одного). Падает в None, если pygame пока не может сообщить.
        try:
            self._instance_id = self._js.get_instance_id()
        except Exception:
            self._instance_id = None
        self._connected = True

#### Публичный API #####################################################################
    @property
    def name(self) -> str:
        return self._js.get_name()

    def is_connected(self) -> bool:
        """True, пока pygame ещё видит этот joystick. Прокачиваем очередь
        событий, чтобы JOYDEVICEREMOVED успел обновить состояние.

        Используется FlightWindow для аварийного disarm, если геймпад
        выдернули в полёте.
        """
        import pygame
        if self._pump_events:
            pygame.event.pump()
        try:
            if pygame.joystick.get_count() <= self._joystick_index:
                return False
            if not self._js.get_init():
                return False
            self._js.get_axis(0)
            return True
        except Exception:
            return False

    def get_stick_positions(self) -> tuple[float, float, float, float]:
        """Возвращает (throttle, yaw, pitch, roll) в диапазоне [-1, 1]."""
        if self._pump_events:
            import pygame
            pygame.event.pump()
        return (
            self._read_axis('thr'),
            self._read_axis('yaw'),
            self._read_axis('pitch'),
            self._read_axis('roll'),
        )

    def is_armed(self) -> bool:
        """Возвращает текущее состояние ARM, при необходимости опрашивая переходы кнопки.

        Пока с момента создания input не зафиксирован DISARM, всегда отдаёт
        False — иначе вход в полёт с тумблером, оставленным в ARM, мгновенно
        армировал бы дрон. После первого DISARM работает обычная логика."""
        raw = self._read_arm_raw()
        if not self._disarm_seen:
            if not raw:
                self._disarm_seen = True
            return False
        return raw

    def _read_arm_raw(self) -> bool:
        arm_type = self._cal.get('arm_type', 'button')
        if arm_type == 'axis':
            idx = self._cal.get('arm_axis_index', 0)
            try:
                return self._js.get_axis(idx) > 0.5
            except Exception:
                return False
        return self._poll_arm_button()

#### Внутренние помощники ##############################################################
    def _read_axis(self, name: str) -> float:
        idx = self._cal.get(f'axis_{name}', 0)
        try:
            raw = self._js.get_axis(idx)
        except Exception:
            return 0.0
        mn = self._cal.get(f'{name}_min', -1.0)
        mx = self._cal.get(f'{name}_max', 1.0)
        center = self._cal.get(f'{name}_center', 0.0)
        if raw >= center:
            span = mx - center
            return (raw - center) / span if span > 0 else 0.0
        span = center - mn
        return -(center - raw) / span if span > 0 else 0.0

    def _poll_arm_button(self) -> bool:
        idx = self._cal.get('arm_button_index', 0)
        try:
            cur = self._js.get_button(idx)
        except Exception:
            return self._arm
        if cur != self._arm_btn_prev:
            self._arm_btn_prev = cur
            if cur == 1:
                self._arm = not self._arm
        return self._arm
