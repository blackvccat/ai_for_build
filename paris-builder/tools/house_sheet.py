"""Render house designs onto one contact sheet, so the three layers can be judged.

Each tile is a real design built from the three databases and rendered with the
project's normal block-model renderer. The street face is the one to look at, and the
renderer's `front` camera already shows it for these forms because their street wall
is built on the north side.

Why a sheet rather than one render at a time: the question this tool answers is whether
a *facade scheme* is independent of a *form*, and that is only visible when the same
scheme appears on several forms side by side.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from PIL import Image, ImageDraw  # noqa: E402

from paris_builder import design  # noqa: E402
from paris_builder.exporter import write_schematic  # noqa: E402
from paris_builder.fonts import load_font  # noqa: E402
from paris_builder.preview3d import render_previews  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def one(form: str, scheme: str, seed: int, work: Path, size: int):
    """Build, export and render one design. Returns (image path, manifest)."""
    plan = design.plan_for(form, seed=seed, scheme=scheme)
    scene, manifest = design.build(plan)
    tag = '%s__%s' % (form, scheme)
    schem = work / ('%s.schem' % tag)
    write_schematic(schem, scene.volume, scene.palette, name=tag)
    paths = render_previews(schem, work / tag, max_size=size)
    return paths['front'], manifest, paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', default='HOUSE-DESIGN-v0.1')
    parser.add_argument('--seed', type=int, default=1900)
    parser.add_argument('--size', type=int, default=560)
    parser.add_argument('--column', default='scheme',
                        choices=['scheme', 'form'],
                        help='what varies down the sheet: one form, many schemes, or the reverse')
    parser.add_argument('--form', default=None, help='fix the form when --column scheme')
    parser.add_argument('--scheme', default=None, help='fix the scheme when --column form')
    parser.add_argument('--cell', type=int, nargs=2, default=[430, 560])
    args = parser.parse_args()

    out = ROOT / 'runs' / args.run
    work = out / 'build'
    work.mkdir(parents=True, exist_ok=True)

    if args.column == 'scheme':
        form = args.form or 'street_house'
        pairs = [(form, name) for name in sorted(design.facade_layer.SCHEMES)]
    else:
        scheme = args.scheme or 'haussmann_apartment'
        pairs = [(name, scheme) for name in sorted(design.structure_layer.FORMS)]

    tiles, rows = [], []
    for form, scheme in pairs:
        image_path, manifest, paths = one(form, scheme, args.seed, work, args.size)
        tiles.append((('%s + %s' % (form, scheme)), image_path, manifest))
        rows.append({'form': form, 'scheme': scheme, 'plan': manifest['plan'],
                     'techniques': manifest['techniques'],
                     'street_openings': next((w['openings'] for w in manifest['walls']
                                              if w['role'] == 'primary'), 0),
                     'render': paths['front']})

    cell_w, cell_h = args.cell
    columns = 2 if len(tiles) > 1 else 1
    sheet_rows = (len(tiles) + columns - 1) // columns
    sheet = Image.new('RGB', (cell_w * columns, cell_h * sheet_rows), (229, 235, 239))
    draw = ImageDraw.Draw(sheet)
    title_font = load_font(13)
    small = load_font(12)
    for index, (label, image_path, manifest) in enumerate(tiles):
        image = Image.open(image_path).convert('RGB')
        image.thumbnail((cell_w - 12, cell_h - 52), Image.Resampling.LANCZOS)
        cx = (index % columns) * cell_w
        cy = (index // columns) * cell_h
        sheet.paste(image, (cx + (cell_w - image.width) // 2, cy + 30))
        # Labels stay ASCII: this host's TrueType backend cannot be trusted with CJK.
        # The counts line is trimmed because a full technique list is wider than a tile.
        draw.text((cx + 8, cy + 8), label, font=title_font, fill=(20, 28, 34))
        counts = ' '.join('%s=%d' % (k, v) for k, v in sorted(manifest['techniques'].items()))
        draw.text((cx + 8, cy + cell_h - 38), counts[:78], font=small, fill=(60, 70, 78))
        draw.text((cx + 8, cy + cell_h - 24),
                  'openings=%d  techniques=%d' % (
                      sum(w['openings'] for w in manifest['walls']), len(manifest['techniques'])),
                  font=small, fill=(60, 70, 78))
        draw.text((cx + 8, cy + cell_h - 12),
                  'cells=%d storeys=%d %dx%dx%d' % (manifest['cells'],
                                                    manifest['structure']['storeys'],
                                                    *manifest['scene_whd']),
                  font=small, fill=(60, 70, 78))
    sheet_path = out / ('sheet_by_%s.png' % args.column)
    sheet.save(sheet_path, optimize=True)
    (out / 'design_sheet.json').write_text(
        json.dumps({'seed': args.seed, 'column': args.column, 'tiles': rows}, indent=2,
                   ensure_ascii=False), encoding='utf-8')
    for item in work.iterdir():
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
    print(json.dumps({'sheet': str(sheet_path.resolve()), 'tiles': len(tiles)}, indent=2))
    return


if __name__ == '__main__':
    raise SystemExit(main())
