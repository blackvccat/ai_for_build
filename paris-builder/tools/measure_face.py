"""Measure what the street face of a city schematic actually consists of.

Reading a render is not enough to tell "the windows are too dark" from "the windows
were never written", and the first three city renders were diagnosed wrongly for
exactly that reason. This walks the outermost non-air cell of every (x, y) column on
a chosen side and reports the material histogram plus the per-column opening pattern,
so a blank wall shows up as numbers rather than as an opinion.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import numpy as np

from paris_builder.schematic import load_schematic, base_block


def face_columns(volume, states, side):
    """For every (x, y) column, the state of the cell first met from outside."""
    height, depth, width = volume.shape
    if side == 'north':
        order, layer = range(depth), 0
    else:
        order, layer = range(depth - 1, -1, -1), 1
    out = np.full((height, width), '', dtype=object)
    for y in range(height):
        for x in range(width):
            for z in order:
                value = states[int(volume[y, z, x])]
                if value and value != 'minecraft:air':
                    out[y, x] = value
                    break
    return out, layer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('schematic', type=Path)
    parser.add_argument('--side', default='south', choices=['north', 'south'])
    args = parser.parse_args()

    data = load_schematic(args.schematic)
    face, layer = face_columns(data.volume, data.id_to_state, args.side)
    height, width = face.shape
    families = Counter(base_block(v) for v in face.ravel() if v)
    print('visible cells by material family (side=%s):' % args.side)
    for name, count in families.most_common(14):
        print('  %-46s %6d' % (name, count))

    openings = ('minecraft:light_gray_concrete', 'minecraft:glass_pane',
                'minecraft:light_gray_stained_glass_pane')
    mask = np.isin(face, openings)
    print('\nopening cells visible: %d of %d (%.1f%%)' % (mask.sum(), face.size, 100.0 * mask.mean()))
    columns = mask.any(axis=0)
    runs = []
    start = None
    for x in range(width):
        if columns[x] and start is None:
            start = x
        elif not columns[x] and start is not None:
            runs.append((start, x - 1))
            start = None
    if start is not None:
        runs.append((start, width - 1))
    print('columns carrying an opening: %d of %d; runs=%d' % (int(columns.sum()), width, len(runs)))
    if runs:
        widths = [b - a + 1 for a, b in runs]
        gaps = [runs[i + 1][0] - runs[i][1] - 1 for i in range(len(runs) - 1)]
        print('  run widths: min=%d max=%d mean=%.1f' % (min(widths), max(widths), sum(widths) / len(widths)))
        if gaps:
            print('  gaps between runs: min=%d max=%d mean=%.1f' % (min(gaps), max(gaps), sum(gaps) / len(gaps)))

    rows = mask.any(axis=1)
    band = [(y, int(rows[y])) for y in range(height)]
    print('\nper-storey opening coverage (y: columns):')
    for y, count in band:
        if count or (y and band[y - 1][1]):
            print('  y=%2d  %s%d' % (y, '#' * min(60, count // 3), count))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
