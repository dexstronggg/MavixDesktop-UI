"""Поиск и запуск QGroundControl с env-переменной SDL_GAMECONTROLLERCONFIG."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from mavixdesktop.core.logger import logger

_QGC_PATH_FILE = Path.home() / '.config' / 'mavixdesktop' / 'qgc_path.txt'

# Параметры ограниченного поиска. Полный рекурсивный обход дисков на Windows
# (rglob по C:/ D:/ E:/) подвешивал GUI на минуты, поэтому поиск жёстко
# ограничен по времени, глубине и числу просмотренных записей.
_SEARCH_DEADLINE_S = 5.0
_SEARCH_MAX_DEPTH = 2
_SEARCH_BUDGET = 20_000


#### Сохранённый путь к QGC ############################################################
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


#### Поиск установленного QGC ##########################################################
def _is_qgc_windows_exe(name: str) -> bool:
    """Совпадает только с установленным QGroundControl.exe.

    Сознательно НЕ startswith('qgroundcontrol'), иначе под совпадение попадает
    инсталлятор QGroundControl-installer-AMD64.exe (обычно лежит в Downloads) и
    прочие сопутствующие .exe. Деинсталлятор Inno Setup называется unins000.exe
    и под точное имя тоже не подходит."""
    return name.lower() == 'qgroundcontrol.exe'


def _is_qgc_linux_file(name: str) -> bool:
    """Бинарь QGroundControl или его AppImage (QGroundControl-x86_64.AppImage,
    QGroundControl-aarch64.AppImage и т.п.)."""
    n = name.lower()
    return n == 'qgroundcontrol' or (n.startswith('qgroundcontrol') and n.endswith('.appimage'))


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
    return _bounded_find(roots, _is_qgc_linux_file, deadline_s)


def _find_qgc_windows(deadline_s: float) -> Path | None:
    for cmd in ('QGroundControl', 'QGroundControl.exe'):
        which = shutil.which(cmd)
        if which:
            return Path(which)

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
    return _bounded_find(roots, _is_qgc_windows_exe, deadline_s)


def find_qgc(deadline_s: float = _SEARCH_DEADLINE_S) -> Path | None:
    """Возвращает путь к QGroundControl: сначала сохранённый, иначе ищет в системе.

    Авто-найденный путь сразу сохраняется, чтобы при следующем запуске не
    искать заново. Поиск ограничен по времени (deadline_s) и глубине, поэтому
    в худшем случае возвращается за ~deadline_s секунд независимо от размера
    диска (раньше rglob по дискам подвешивал GUI на минуты).
    """
    saved = get_saved_qgc_path()
    if saved is not None:
        return saved
    # сохранённый путь был, но файл исчез — удалим, чтобы не врать в логах
    if _QGC_PATH_FILE.exists():
        clear_saved_qgc_path()
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


def launch_qgc(sdl_config: str = '', qgc_path: Path | None = None) -> subprocess.Popen | None:
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
