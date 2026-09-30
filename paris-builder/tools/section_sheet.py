#!/usr/bin/env python3
"""Render the mined facade sections into one visual sheet.

A section library is only useful if the facade fragments it contains are actually
what a facade should be made of, so this renders each promoted section with the
real block-model renderer and lays them out for human review.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from paris_builder.exporter import write_schematic  # noqa: E402
from paris_builder.fonts import load_font  # noqa: E402
from paris_builder.preview3d import render_previews  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path, default=ROOT / 'knowledge/library-v1/source-sections')
    parser.add_argument('--limit', type=int, default=9)
    parser.add_argument('--render-size', type=int, default=240)
    args = parser.parse_args()

    sections = json.loads((args.library / 'sections.json').read_text(encoding='utf-8'))
    ranked = sorted(sections, key=lambda s: (-s['occurrences'], s['recipe_id']))[:args.limit]
    out = ROOT / 'runs/MODEL-DESIGN-SECTION-SHEET'
    tiles_dir = out / 'tiles'
    tiles_dir.mkdir(parents=True, exist_ok=True)

    tiles = []
    for entry in ranked:
        width, depth, height = entry['dimensions_wdh']
        volume = np.zeros((height, depth, width), dtype=np.int32)
        for x, z, y, value in entry['voxels']:
            volume[y, z, x] = value
        schem = tiles_dir / (entry['recipe_id'] + '.schem')
        write_schematic(schem, volume, entry['palette'], name=entry['recipe_id'])
        paths = render_previews(schem, tiles_dir / entry['recipe_id'], max_size=args.render_size, orbit=False)
        tiles.append((entry, Path(paths['axonometric_front'])))

    size = args.render_size
    label = 30
    columns = 3
    rows = (len(tiles) + columns - 1) // columns
    sheet = Image.new('RGB', (columns * size + 20, rows * (size + label) + 40), '#eef1f4')
    draw = ImageDraw.Draw(sheet)
    draw.text((10, 8), 'Mined source facade sections (one storey, several bays) | '
                       'label: occurrences x bays, width x depth x height', font=load_font(16), fill='#1f2a33')
    for index, (entry, path) in enumerate(tiles):
        column, row = index % columns, index // columns
        x = 10 + column * size
        y = 40 + row * (size + label)
        text = 'x%d  %dbay  %dx%dx%d' % (entry['occurrences'], entry['bays'],
                                         entry['dimensions_wdh'][0], entry['dimensions_wdh'][1],
                                         entry['dimensions_wdh'][2])
        draw.text((x, y), text, font=load_font(14), fill='#33414d')
        sheet.paste(Image.open(path).convert('RGB').resize((size - 8, size - 8)), (x, y + label))
    sheet_path = ROOT / 'runs/MODEL-DESIGN-SECTION-SHEET.png'
    sheet.save(sheet_path, optimize=True)
    (ROOT / 'runs/MODEL-DESIGN-SECTION-SHEET.json').write_text(json.dumps(
        {'sheet': str(sheet_path), 'sections': [entry['recipe_id'] for entry, _ in tiles],
         'note': 'Sections are single-storey source facade fragments; occurrence count is how often '
                 'the same fragment repeats across the 14 builds.'}, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8')
    print('sheet:', sheet_path, sheet.size, '| sections:', len(tiles))


if __name__ == '__main__':
    main()
