"""Генератор иконок Mavix для сборки дистрибутивов.

Вызывается из ``scripts/build_windows.ps1`` и ``scripts/build_linux.sh`` для
создания .ico (Windows) и .png (Linux) из ``mavix_logo_pixmap``. Без
этого скрипта пришлось бы держать бинарные .ico/.png в репозитории.

Использование:

    python scripts/_make_icon.py --format png --output dist/icon.png --size 256
    python scripts/_make_icon.py --format ico --output dist/icon.ico

Для .ico требуется Pillow (Qt напрямую умеет писать ICO, но только
single-size; multi-size делается через PIL.Image.save(..., sizes=...)).
"""
from __future__ import annotations

import argparse
import sys
from io import BytesIO
from pathlib import Path

# Запускается как одиночный скрипт без установленного пакета —
# добавляем src/ в path чтобы можно было импортировать
# mavixdesktop.ui.screens.utils.mavix_logo_pixmap.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / 'src'))

from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mavixdesktop.ui.screens.utils import mavix_logo_pixmap  # noqa: E402


_ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48),
              (64, 64), (128, 128), (256, 256)]


def main() -> None:
    parser = argparse.ArgumentParser(description='Mavix icon generator')
    parser.add_argument('--format', choices=('png', 'ico'), required=True,
                        help='тип выходного файла')
    parser.add_argument('--output', required=True, type=Path,
                        help='путь к выходному файлу')
    parser.add_argument('--size', type=int, default=256,
                        help='размер для PNG (по умолчанию 256). На ICO не влияет.')
    args = parser.parse_args()

    # QPixmap требует QGuiApplication — создаём минимальное QApplication
    # без exec()/show(). Hidden для CI/headless контекстов.
    _app = QApplication.instance() or QApplication(sys.argv)

    args.output.parent.mkdir(parents=True, exist_ok=True)

    if args.format == 'png':
        pixmap = mavix_logo_pixmap(args.size)
        if not pixmap.save(str(args.output), 'PNG'):
            sys.exit(f'не удалось сохранить PNG в {args.output}')
        print(f'PNG записан: {args.output} ({args.size}x{args.size})')
        return

    # ICO multi-size: рендерим базовую 256×256 в QBuffer, передаём в
    # Pillow для финального ICO с набором стандартных размеров.
    try:
        from PIL import Image
    except ImportError:
        sys.exit('Для .ico требуется Pillow: pip install pillow')

    base = mavix_logo_pixmap(256)
    qbuf = QBuffer()
    qbuf.open(QIODevice.OpenModeFlag.WriteOnly)
    if not base.save(qbuf, 'PNG'):
        sys.exit('не удалось сериализовать base PNG в QBuffer')
    png_bytes = bytes(qbuf.data())
    qbuf.close()

    img = Image.open(BytesIO(png_bytes))
    img.save(str(args.output), format='ICO', sizes=_ICO_SIZES)
    print(f'ICO записан: {args.output} (sizes={len(_ICO_SIZES)})')


if __name__ == '__main__':
    main()
