"""Поиск и запуск QGroundControl с env-переменной SDL_GAMECONTROLLERCONFIG."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

from mavixdesktop.core.logger import logger

_QGC_PATH_FILE = Path.home() / '.config' / 'mavixdesktop' / 'qgc_path.txt'


def get_saved_qgc_path() -> Path | None:
    try:
        text = _QGC_PATH_FILE.read_text(encoding='utf-8').strip()
    except (FileNotFoundError, PermissionError, OSError):
        return None
    if not text:
        return None
    p = Path(text)
    return p if p.is_file() else None


def save_qgc_path(path: Path) -> None:
    try:
        _QGC_PATH_FILE.parent.mkdir(parents=True, exist_ok=True)
        _QGC_PATH_FILE.write_text(str(path), encoding='utf-8')
        logger.info('[qgc] сохранён пользовательский путь: %s', path)
    except OSError as exc:
        logger.warning('[qgc] не удалось сохранить пользовательский путь: %s', exc)


def clear_saved_qgc_path() -> None:
    try:
        _QGC_PATH_FILE.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning('[qgc] не удалось очистить пользовательский путь: %s', exc)


def _looks_like_qgc(name: str) -> bool:
    n = name.lower()
    return n.startswith('qgroundcontrol') or n.startswith('qground_control') or n.startswith('qground-control')


def _find_qgc_linux() -> Path | None:
    for cmd in ('QGroundControl', 'qgroundcontrol'):
        which = shutil.which(cmd)
        if which:
            return Path(which)
    home = Path.home()
    try:
        for f in home.rglob('*'):
            if f.is_file() and _looks_like_qgc(f.name) and f.name.endswith('.AppImage'):
                return f
    except PermissionError:
        pass
    for sys_dir in (Path('/opt'), Path('/usr/local'), Path('/usr/bin')):
        try:
            for f in sys_dir.rglob('*'):
                if f.is_file() and 'qgroundcontrol' in f.name.lower():
                    return f
        except PermissionError:
            pass
    return None


def _find_qgc_windows() -> Path | None:
    for cmd in ('QGroundControl', 'QGroundControl.exe'):
        which = shutil.which(cmd)
        if which:
            return Path(which)
    candidate_roots = [
        Path.home(),
        Path(os.environ.get('PROGRAMFILES') or r'C:\Program Files'),
        Path(os.environ.get('PROGRAMFILES(X86)') or r'C:\Program Files (x86)'),
        Path(os.environ.get('LOCALAPPDATA') or ''),
        Path(os.environ.get('APPDATA') or ''),
        Path(os.environ.get('PROGRAMDATA') or r'C:\ProgramData'),
        Path('C:/'), Path('D:/'), Path('E:/'),
    ]
    seen: set[Path] = set()
    for root in candidate_roots:
        if str(root) in ('', '.'):
            continue
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.is_dir():
            continue
        seen.add(resolved)
        try:
            for f in resolved.rglob('*.exe'):
                if _looks_like_qgc(f.name):
                    return f
        except (PermissionError, OSError):
            pass
    return None


def find_qgc() -> Path | None:
    saved = get_saved_qgc_path()
    if saved is not None:
        return saved
    # сохранённый путь был, но файл исчез — удалим, чтобы не врать в логах
    if _QGC_PATH_FILE.exists():
        clear_saved_qgc_path()
    system = platform.system()
    if system == 'Linux':
        return _find_qgc_linux()
    if system == 'Windows':
        return _find_qgc_windows()
    return None


# QGroundControl сам реализует single-instance через QSharedMemory с
# фиксированным ключом «QGroundControlRunGuardKey» (см. src/RunGuard.h в
# mavlink/qgroundcontrol). Сегмент создаёт сам GUI-процесс QGC и
# освобождает при выходе. AppImage/.deb wrapper его НЕ создаёт, поэтому
# attach к этому ключу — единственный честный признак «QGC реально
# открыт». Pgrep / /proc / Popen.poll давали ложные срабатывания именно
# потому, что ловили wrapper-родителя, переживающего закрытие GUI.
_QGC_RUNGUARD_KEY = 'QGroundControlRunGuardKey'

_last_launched_proc: subprocess.Popen | None = None


def is_qgc_running() -> bool:
    try:
        from PySide6.QtCore import QSharedMemory
    except ImportError:
        # Без Qt можем только глянуть на наш собственный Popen.
        proc = _last_launched_proc
        return proc is not None and proc.poll() is None
    shm = QSharedMemory(_QGC_RUNGUARD_KEY)
    if shm.attach():
        shm.detach()
        return True
    return False


def launch_qgc(sdl_config: str = '') -> subprocess.Popen | None:
    qgc_path = find_qgc()
    if not qgc_path:
        logger.warning('[qgc] QGroundControl не найден')
        return None
    logger.info('[qgc] найден %s', qgc_path)
    env = os.environ.copy()
    if sdl_config:
        env['SDL_GAMECONTROLLERCONFIG'] = sdl_config
    global _last_launched_proc
    try:
        proc = subprocess.Popen(
            [str(qgc_path)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info('[qgc] запущен pid=%d', proc.pid)
        _last_launched_proc = proc
        return proc
    except Exception as exc:
        logger.error('[qgc] запуск не удался: %s', exc)
        return None
