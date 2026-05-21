"""Генератор иконок Mavix для сборки дистрибутивов.

Вызывается из ``scripts/build_windows.ps1`` и ``scripts/build_linux.sh``
для создания .ico (Windows) и .png (Linux). Без этого скрипта пришлось
бы держать бинарные .ico/.png в репозитории.

Реализация дублирует логику ``mavixdesktop.ui.screens.utils.mavix_logo_pixmap``
(cyan-градиентный rounded square + центрированная буква «M»), но через
Pillow + NumPy вместо PySide6 — потому что:

* PySide6 на CI/headless-машинах требует libGL.so.1 (mesa) для импорта,
  это лишняя системная зависимость на сборочной машине;
* Pillow умеет писать multi-size .ico одной строкой (Qt-API делает
  только single-size, иконка размывается на 16/32px иконке трея).

Использование:

    python scripts/_make_icon.py --format png --output dist/icon.png --size 256
    python scripts/_make_icon.py --format ico --output dist/icon.ico
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:
    sys.exit(f'требуется numpy + pillow: pip install pillow numpy ({exc})')


# Градиент: ACCENT (#22d3ee) → ACCENT_PRESS (#06b6d4), диагональ TL→BR.
# Те же цвета, что и в mavix_logo_pixmap.
_GRAD_START = (0x22, 0xd3, 0xee)
_GRAD_END   = (0x06, 0xb6, 0xd4)
# Цвет «M» — почти-чёрный с лёгким cyan-уклоном (#001017).
_LETTER_COLOR = (0x00, 0x10, 0x17, 0xff)
# Стандартный набор размеров для multi-size .ico (Windows ресолвит
# нужный сам по контексту: tray vs alt-tab vs explorer).
_ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48),
              (64, 64), (128, 128), (256, 256)]


def _gradient_image(size: int) -> Image.Image:
    """Cyan-градиент через NumPy: каждая точка линейно интерполируется
    между _GRAD_START и _GRAD_END по диагонали."""
    y, x = np.meshgrid(np.arange(size), np.arange(size), indexing='ij')
    t = (x + y) / (2 * max(size - 1, 1))  # 0..1 по диагонали
    r = (_GRAD_START[0] * (1 - t) + _GRAD_END[0] * t).astype(np.uint8)
    g = (_GRAD_START[1] * (1 - t) + _GRAD_END[1] * t).astype(np.uint8)
    b = (_GRAD_START[2] * (1 - t) + _GRAD_END[2] * t).astype(np.uint8)
    a = np.full_like(r, 255)
    arr = np.stack([r, g, b, a], axis=-1)
    return Image.fromarray(arr, 'RGBA')


def _load_letter_font(target_px: int) -> ImageFont.ImageFont:
    """Шрифт для «M». Пытается найти жирный sans-serif. Fallback —
    дефолтный PIL bitmap font (не масштабируется красиво, но иконка
    хотя бы соберётся)."""
    candidates = [
        'Inter-Bold.ttf',  # из ресурсов, если кто-то положил рядом
        # Системные жирные sans-шрифты по убыванию предпочтения:
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',  # Debian/Ubuntu
        '/usr/share/fonts/TTF/DejaVuSans-Bold.ttf',              # Arch
        '/Library/Fonts/Arial Bold.ttf',                          # macOS
        'C:/Windows/Fonts/arialbd.ttf',                           # Windows
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, target_px)
        except (OSError, IOError):
            continue
    # Last resort — bitmap font, выглядит хуже но работает.
    return ImageFont.load_default()


def mavix_logo_image(size: int) -> Image.Image:
    """Cyan rounded square с центрированной буквой «M».

    Эквивалент `mavix_logo_pixmap` из ui/screens/utils.py, но на Pillow.
    """
    # Маска — rounded rectangle. radius = 26% от размера, как в Qt-версии.
    radius = int(size * 0.26)
    mask = Image.new('L', (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=radius, fill=255,
    )

    # Заливка: cyan-градиент под mask.
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    img.paste(_gradient_image(size), (0, 0), mask)

    # Буква «M» — bold, ≈62% высоты иконки.
    font = _load_letter_font(int(size * 0.62))
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), 'M', font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    # Корректировка под bbox (textbbox даёт offset из-за метрик шрифта).
    x = (size - text_w) / 2 - bbox[0]
    y = (size - text_h) / 2 - bbox[1]
    draw.text((x, y), 'M', font=font, fill=_LETTER_COLOR)

    return img


def main() -> None:
    parser = argparse.ArgumentParser(description='Mavix icon generator')
    parser.add_argument('--format', choices=('png', 'ico'), required=True,
                        help='тип выходного файла')
    parser.add_argument('--output', required=True, type=Path,
                        help='путь к выходному файлу')
    parser.add_argument('--size', type=int, default=256,
                        help='размер для PNG (по умолчанию 256). На ICO не влияет.')
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    if args.format == 'png':
        img = mavix_logo_image(args.size)
        img.save(str(args.output), format='PNG')
        print(f'PNG записан: {args.output} ({args.size}x{args.size})')
        return

    # ICO multi-size: Pillow собирает мульти-фреймовый ICO из одной
    # большой 256×256 иконки, downsampling делает сам.
    base = mavix_logo_image(256)
    base.save(str(args.output), format='ICO', sizes=_ICO_SIZES)
    print(f'ICO записан: {args.output} (sizes={len(_ICO_SIZES)})')


if __name__ == '__main__':
    main()
