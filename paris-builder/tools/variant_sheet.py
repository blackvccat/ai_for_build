#!/usr/bin/env python3
"""Build a side-by-side contact sheet of measured geometry variants.

Iterating against the visual critic alone did not beat the recorded baseline, so
this collects the renders a human needs in one image instead of leaving them
scattered across run directories. Read-only on the runs; writes one PNG.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from paris_builder.fonts import load_font  # noqa: E402

VARIANTS = [
    ('baseline fw2 (77)', ROOT / 'runs/MODEL-DESIGN-LIVE-v0.8/frameworks/fw2/previews/axonometric_front.png'),
    ('plain, no ornament (75)', ROOT / 'runs/MODEL-DESIGN-CRITIC-PLAIN/candidate/previews/axonometric_front.png'),
    ('B2 crown+cornice (74)', ROOT / 'runs/MODEL-DESIGN-CRITIC-AFTER-B2/candidate/previews/axonometric_front.png'),
    ('B3 wide shops (73)', ROOT / 'runs/MODEL-DESIGN-CRITIC-AFTER-B3/candidate/previews/axonometric_front.png'),
    ('B4 deep mansard+pavilion (69)', ROOT / 'runs/MODEL-DESIGN-CRITIC-MASSING/candidate/previews/axonometric_front.png'),
]

TILE = 420
PAD = 16
LABEL = 26


def main():
    cells = []
    for label, path in VARIANTS:
        if not path.is_file():
            print('missing:', path)
            continue
        image = Image.open(path).convert('RGB')
        image.thumbnail((TILE, TILE))
        cells.append((label, image))
    if not cells:
        raise SystemExit('no variant renders found')
    columns = 3
    rows = (len(cells) + columns - 1) // columns
    width = columns * (TILE + PAD) + PAD
    height = rows * (TILE + LABEL + PAD) + PAD + LABEL
    sheet = Image.new('RGB', (width, height), '#eef1f4')
    draw = ImageDraw.Draw(sheet)
    font = load_font(18)
    small = load_font(14)
    # ASCII only: this machine's TrueType probe fails, so the fallback is Pillow's
    # built-in bitmap font, which cannot encode non Latin-1 punctuation.
    draw.text((PAD, 8), 'MODEL-DESIGN geometry variants, same concept, front axonometric | '
                        'label = visual critic total (baseline 77)', font=font, fill='#1f2a33')
    for index, (label, image) in enumerate(cells):
        column, row = index % columns, index // columns
        x = PAD + column * (TILE + PAD)
        y = PAD + LABEL + row * (TILE + LABEL + PAD)
        draw.text((x, y), label, font=small, fill='#33414d')
        sheet.paste(image, (x, y + LABEL))
    out = ROOT / 'runs/MODEL-DESIGN-VARIANT-SHEET.png'
    sheet.save(out, optimize=True)
    manifest = {'sheet': str(out), 'variants': [{'label': label, 'source': str(path)}
                                                for label, path in VARIANTS if path.is_file()],
                'note': 'Scores are provider-neutral critic measurements of geometry variants; '
                        'none exceeded the 77 baseline. Human judgement decides which direction to keep.'}
    (ROOT / 'runs/MODEL-DESIGN-VARIANT-SHEET.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
                                                               encoding='utf-8')
    print('sheet:', out, sheet.size)


if __name__ == '__main__':
    main()
