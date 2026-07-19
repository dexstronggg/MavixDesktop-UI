"""Joystick discovery + SDL config string generation. Axes are not read here."""
from __future__ import annotations

import platform


def list_joysticks() -> list[str]:
    import pygame
    pygame.joystick.init()
    pygame.event.pump()
    return [
        pygame.joystick.Joystick(i).get_name()
        for i in range(pygame.joystick.get_count())
    ]


def build_sdl_config(cal: dict, name: str, guid: str) -> str:
    def axis_str(sdl_key: str, cal_key: str, inverted: bool) -> str:
        ax = cal.get(f'axis_{cal_key}', 0)
        suffix = '~' if inverted else ''
        return f'{sdl_key}:a{ax}{suffix}'

    thr_inv   = cal.get('thr_max',   1.0) < cal.get('thr_min',   -1.0)
    pitch_inv = cal.get('pitch_max', 1.0) < cal.get('pitch_min', -1.0)
    yaw_inv   = cal.get('yaw_max',   1.0) < cal.get('yaw_min',   -1.0)
    roll_inv  = cal.get('roll_max',  1.0) < cal.get('roll_min',  -1.0)

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
