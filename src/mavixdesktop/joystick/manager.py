"""Обнаружение joystick + генерация SDL-конфиг-строки. Оси здесь не читаются."""
from __future__ import annotations

import platform


def list_joysticks() -> list[str]:
    """Возвращает имена всех подключённых joystick через pygame.

    Импортирует pygame лениво, чтобы тесты, не трогающие реальное
    устройство, не были обязаны его подтягивать.

    quit()+init() — единственный надёжный способ заставить SDL пере-
    перечислить устройства после hot-plug: повторный init() при уже поднятой
    подсистеме НЕ пересканирует, а event.pump() ловит JOYDEVICEADDED только
    когда SDL/udev успел доставить событие (на практике до ~15 с задержки —
    джойстик «появлялся» через четверть минуты). Полная переинициализация
    сканирует /dev/input заново сразу, поэтому устройство видно в пределах
    одного тика авто-обновления (3 с).

    БЕЗОПАСНОСТЬ: quit() освобождает все SDL_Joystick* — нельзя вызывать,
    пока живы Python-объекты Joystick (use-after-free → SIGSEGV). Эта функция
    вызывается только из JoystickSetupPage, чей auto-refresh таймер
    останавливается (а) на время открытых диалогов калибровки/превью, которые
    держат живой Joystick, и (б) через hideEvent до запуска QGC (EVIOCGRAB).
    Поэтому в момент вызова живых Joystick-объектов нет.
    """
    import pygame
    pygame.joystick.quit()
    pygame.joystick.init()
    try:
        return [
            pygame.joystick.Joystick(i).get_name()
            for i in range(pygame.joystick.get_count())
        ]
    except Exception:
        return []


def build_sdl_config(cal: dict, name: str, guid: str) -> str:
    """Собирает строку формата SDL_GAMECONTROLLERCONFIG из словаря калибровки.

    Используется интеграцией с QGroundControl, чтобы тот интерпретировал оси
    joystick так же, как desktop. Инверсия направления выводится из границ
    min/max калибровки (max < min означает, что сырая ось инвертирована).
    """
    def axis_str(sdl_key: str, cal_key: str, inverted: bool) -> str:
        ax = cal.get(f'axis_{cal_key}', 0)
        suffix = '~' if inverted else ''
        return f'{sdl_key}:a{ax}{suffix}'

    thr_inv   = cal.get('thr_max',   1.0) < cal.get('thr_min',   -1.0)
    pitch_inv = cal.get('pitch_max', 1.0) < cal.get('pitch_min', -1.0)
    yaw_inv   = cal.get('yaw_max',   1.0) < cal.get('yaw_min',   -1.0)
    roll_inv  = cal.get('roll_max',  1.0) < cal.get('roll_min',  -1.0)

    # SDL lefty/righty ожидают up=-1; если сырое up > 0, нужна инверсия (~)
    lefty_inv  = not thr_inv
    righty_inv = not pitch_inv

    parts = [
        guid, name,
        axis_str('leftx',  'yaw',   yaw_inv),
        axis_str('lefty',  'thr',   lefty_inv),
        axis_str('rightx', 'roll',  roll_inv),
        axis_str('righty', 'pitch', righty_inv),
        f'a:b{cal.get("arm_button_index", 0)}',
        f'platform:{platform.system()}',
    ]
    return ','.join(parts)
