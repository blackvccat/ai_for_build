#!/usr/bin/env python3
"""Contact sheet of the 14 source builds, for classifying their massing forms.

Reading them one at a time hides the point: they are not 14 variations of one
apartment type. This sheet is the input to the structure library (a building's form
is chosen before its facades), so the typology has to come from looking at all of
them together.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from paris_builder.fonts import load_font  # noqa: E402

TILE = 300
LABEL = 24
COLUMNS = 4


def ascii_label(name):
    """ASCII-only label: this host's TrueType probe fails, so the bitmap fallback
    font (Latin-1 only) is used and Chinese file names cannot be drawn."""
    cleaned = name.replace('巴黎建筑素材', 'building').replace('巴黎民居街区', 'street')
    cleaned = cleaned.replace('[斜面建筑]', '-slope').replace('修改版', '-mod')
    return ''.join(ch if ord(ch) < 128 else '_' for ch in cleaned)


def main():
    images = sorted((ROOT.parent / '巴黎建筑素材').glob('*.png'))
    if not images:
        raise SystemExit('no source overview renders found')
    cells = []
    for path in images:
        image = Image.open(path).convert('RGB')
        image.thumbnail((TILE, TILE))
        cells.append((ascii_label(path.stem), image))
    rows = (len(cells) + COLUMNS - 1) // COLUMNS
    sheet = Image.new('RGB', (COLUMNS * TILE + 20, rows * (TILE + LABEL) + 44), '#eef1f4')
    draw = ImageDraw.Draw(sheet)
    draw.text((10, 8), '14 source builds - massing forms (structure library input)',
              font=load_font(18), fill='#1f2a33')
    for index, (name, image) in enumerate(cells):
        column, row = index % COLUMNS, index // COLUMNS
        x = 10 + column * TILE
        y = 44 + row * (TILE + LABEL)
        draw.text((x, y), name, font=load_font(14), fill='#33414d')
        sheet.paste(image, (x, y + LABEL))
    out = ROOT / 'runs/SOURCE-FORMS-SHEET.png'
    sheet.save(out, optimize=True)
    print('sheet:', out, sheet.size, '| sources:', len(cells))


if __name__ == '__main__':
    main()
