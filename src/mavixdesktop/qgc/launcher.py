"""Поиск и запуск QGroundControl с env-переменной SDL_GAMECONTROLLERCONFIG."""
from __future__ import annotations

import contextlib
import os
import platform
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from mavixdesktop.core import user_config
from mavixdesktop.core.logger import logger

# Ключ в config.json, где лежит выбранный/найденный путь к QGroundControl.
_QGC_PATH_KEY = 'qgc_path'

# Параметры ограниченного поиска. Полный рекурсивный обход дисков на Windows
# (rglob по C:/ D:/ E:/) подвешивал GUI на минуты, поэтому поиск жёстко
# ограничен по времени, глубине и числу просмотренных записей.
_SEARCH_DEADLINE_S = 5.0
_SEARCH_MAX_DEPTH = 2
_SEARCH_BUDGET = 20_000


def _legacy_path_file() -> Path:
    """Старое место хранения пути (plain-text), которое мигрируем в config.json."""
    return Path.home() / '.config' / 'mavixdesktop' / 'qgc_path.txt'


#### Сохранённый путь к QGC ############################################################
def get_saved_qgc_path() -> Path | None:
    """Возвращает сохранённый путь к QGC из config.json, если файл всё ещё на месте.

    Если ключа нет — пробует одноразовую миграцию из старого qgc_path.txt.
    Если путь записан, но файл по нему исчез, — чистит ключ и возвращает None,
    чтобы вызвавший заново спросил путь у пользователя.
    """
    raw = user_config.load().get(_QGC_PATH_KEY)
    if not raw:
        return _migrate_legacy_path()
    p = Path(str(raw))
    if p.is_file():
        return p
    clear_saved_qgc_path()
    return None


def save_qgc_path(path: Path) -> None:
    data = user_config.load()
    data[_QGC_PATH_KEY] = str(path)
    try:
        user_config.save(data)
        logger.info('[qgc] сохранён путь к QGroundControl: %s', path)
    except OSError as exc:
        logger.warning('[qgc] не удалось сохранить путь: %s', exc)


def clear_saved_qgc_path() -> None:
    data = user_config.load()
    if _QGC_PATH_KEY not in data:
        return
    data.pop(_QGC_PATH_KEY, None)
    try:
        user_config.save(data)
    except OSError as exc:
        logger.warning('[qgc] не удалось очистить путь: %s', exc)


def _migrate_legacy_path() -> Path | None:
    """Переносит путь из старого qgc_path.txt в config.json (одноразово)."""
    legacy = _legacy_path_file()
    try:
        text = legacy.read_text(encoding='utf-8').strip()
    except (FileNotFoundError, PermissionError, OSError):
        return None
    # Файл больше не нужен независимо от валидности содержимого.
    with contextlib.suppress(OSError):
        legacy.unlink()
    if not text:
        return None
    p = Path(text)
    if not p.is_file():
        return None
    save_qgc_path(p)
    logger.info('[qgc] путь перенесён из qgc_path.txt в config.json')
    return p


#### Поиск установленного QGC ##########################################################
def _looks_like_qgc(name: str) -> bool:
    n = name.lower()
    return (
        n.startswith('qgroundcontrol')
        or n.startswith('qground_control')
        or n.startswith('qground-control')
    )


def _bounded_find(
    roots: list[Path],
    predicate: Callable[[str], bool],
    deadline_s: float,
) -> Path | None:
    """Итеративный поиск файла по predicate в нескольких корнях.

    Глубина, число просмотренных записей и время жёстко ограничены, поэтому
    в худшем случае функция возвращается за ~deadline_s секунд независимо от
    размера диска. В каталоги-симлинки/junction не заходим (только реальные
    подкаталоги), что исключает зацикливание.
    """
    start = time.monotonic()
    scanned = 0
    visited: set[str] = set()
    stack: list[tuple[Path, int]] = [(r, 0) for r in roots]
    while stack:
        if time.monotonic() - start > deadline_s:
            logger.debug('[qgc] поиск прерван по дедлайну (%.1fs)', deadline_s)
            return None
        if scanned > _SEARCH_BUDGET:
            logger.debug('[qgc] поиск прерван по бюджету (%d записей)', scanned)
            return None
        current, depth = stack.pop()
        try:
            real = os.path.realpath(current)
        except OSError:
            continue
        if real in visited:
            continue
        visited.add(real)
        try:
            with os.scandir(current) as it:
                for entry in it:
                    scanned += 1
                    try:
                        if entry.is_file() and predicate(entry.name):
                            return Path(entry.path)
                        if (
                            depth < _SEARCH_MAX_DEPTH
                            and entry.is_dir(follow_symlinks=False)
                        ):
                            stack.append((Path(entry.path), depth + 1))
                    except OSError:
                        continue
        except (NotADirectoryError, PermissionError, OSError):
            continue
    return None


def _find_qgc_linux(deadline_s: float) -> Path | None:
    for cmd in ('QGroundControl', 'qgroundcontrol'):
        which = shutil.which(cmd)
        if which:
            return Path(which)
    home = Path.home()
    roots = [
        home / 'Downloads',
        home / 'Applications',
        home / 'Desktop',
        home / '.local' / 'bin',
        home / 'Apps',
        Path('/opt'),
        Path('/usr/local/bin'),
        Path('/usr/bin'),
    ]
    roots = [r for r in roots if r.is_dir()]
    return _bounded_find(roots, _looks_like_qgc, deadline_s)


def _find_qgc_windows(deadline_s: float) -> Path | None:
    for cmd in ('QGroundControl', 'QGroundControl.exe'):
        which = shutil.which(cmd)
        if which:
            return Path(which)

    def is_qgc_exe(name: str) -> bool:
        return name.lower().endswith('.exe') and _looks_like_qgc(name)

    home = Path.home()
    prog = Path(os.environ.get('PROGRAMFILES') or r'C:\Program Files')
    prog_x86 = Path(os.environ.get('PROGRAMFILES(X86)') or r'C:\Program Files (x86)')
    local = Path(os.environ.get('LOCALAPPDATA') or '')
    roots = [
        prog / 'QGroundControl',
        prog_x86 / 'QGroundControl',
        prog,
        prog_x86,
        local / 'Programs',
        home / 'Downloads',
        home / 'Desktop',
        home,
    ]
    roots = [r for r in roots if str(r) not in ('', '.') and r.is_dir()]
    return _bounded_find(roots, is_qgc_exe, deadline_s)


def find_qgc(deadline_s: float = _SEARCH_DEADLINE_S) -> Path | None:
    """Возвращает путь к QGroundControl: сначала сохранённый, иначе ищет в системе.

    Авто-найденный путь сразу сохраняется в config.json, чтобы при следующем
    запуске не искать заново. Поиск ограничен по времени (deadline_s) и не
    блокирует надолго — вызывать его всё равно лучше в фоновом потоке.
    """
    saved = get_saved_qgc_path()
    if saved is not None:
        return saved
    system = platform.system()
    if system == 'Linux':
        found = _find_qgc_linux(deadline_s)
    elif system == 'Windows':
        found = _find_qgc_windows(deadline_s)
    else:
        return None
    if found is not None:
        save_qgc_path(found)
    return found


#### Запуск и контроль процесса ########################################################
# QGroundControl сам реализует single-instance через QSharedMemory с
# фиксированным ключом «QGroundControlRunGuardKey» (см. src/RunGuard.h в
# mavlink/qgroundcontrol). Сегмент создаёт сам GUI-процесс QGC и
# освобождает при выходе. AppImage/.exe wrapper его НЕ создаёт, поэтому
# attach к этому ключу — единственный честный признак «QGC реально
# открыт». Pgrep / /proc / Popen.poll давали ложные срабатывания именно
# потому, что ловили wrapper-родителя, переживающего закрытие GUI.
_QGC_RUNGUARD_KEY = 'QGroundControlRunGuardKey'

_last_launched_proc: subprocess.Popen[bytes] | None = None


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


def launch_qgc(sdl_config: str = '', qgc_path: Path | None = None) -> subprocess.Popen[bytes] | None:
    """Запускает QGC. Путь можно передать явно (например, найденный в фоне);
    иначе ищется через find_qgc()."""
    if qgc_path is None:
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
