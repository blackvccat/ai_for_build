#!/usr/bin/env python3
"""Measure parcel frontage and depth out of the user's own multi-unit street builds.

The city layer needs real dimensions, and the source builds contain whole streets.
A continuous street wall is segmented by vertical breaks (party walls) that run
deeper than the facade; this measures those segments so the parcel ranges in
knowledge/city/ can be checked against the user's material rather than literature
alone.

Read-only. Reports measured frontages, depths and storey counts.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from paris_builder.schematic import load_schematic  # noqa: E402

AIR = ('air', 'cave_air', 'void_air')


def names_of(src):
    lookup = np.array([s.split('[')[0].replace('minecraft:', '') for s in src.id_to_state])
    return lookup[src.volume]


def measure(path):
    src = load_schematic(path)
    solid = ~np.isin(names_of(src), AIR)
    occupied = solid.any(axis=0)                       # (z, x)
    if not occupied.any():
        return None
    # The street facade is the outer envelope; frontage segments are the runs of
    # occupied columns along that face.
    z_rows = np.nonzero(occupied.any(axis=1))[0]
    front_z = z_rows[0]
    front = occupied[front_z]
    xs = np.nonzero(front)[0]
    if len(xs) == 0:
        return None
    runs, start = [], xs[0]
    for a, b in zip(xs, xs[1:]):
        if b - a > 1:
            runs.append((start, a)); start = b
    runs.append((start, xs[-1]))
    frontage = [int(b - a + 1) for a, b in runs]
    # Depth: how far the mass runs behind the facade at the widest column.
    depths = []
    for x in xs[::max(1, len(xs) // 20)]:
        column = np.nonzero(occupied[:, x])[0]
        if len(column):
            depths.append(int(column[-1] - column[0] + 1))
    heights = []
    for x in xs[::max(1, len(xs) // 20)]:
        column = np.nonzero(solid[:, :, x].any(axis=1))[0]
        if len(column):
            heights.append(int(column[-1] - column[0] + 1))
    return {'source': path.name, 'frontage_segments': [int(v) for v in frontage],
            'depth_blocks': [int(v) for v in depths],
            'height_blocks': [int(v) for v in heights],
            'envelope_whd': [int(src.width), int(src.height), int(src.length)]}


def main():
    targets = sys.argv[1:]
    paths = ([Path(t) for t in targets] if targets else
             sorted((ROOT.parent / '巴黎建筑素材').glob('*.schem')))
    report = []
    for path in paths:
        if not path.is_file():
            continue
        result = measure(path)
        if result is None:
            continue
        report.append(result)
        fronts = result['frontage_segments']
        print('%-26s envelope=%s  frontages=%s' % (path.name[:26], result['envelope_whd'], fronts[:12]))
        if result['depth_blocks']:
            print('%-26s depth blocks: median %d, range %d..%d | height median %d'
                  % ('', int(np.median(result['depth_blocks'])), min(result['depth_blocks']),
                     max(result['depth_blocks']), int(np.median(result['height_blocks']))))
    out = ROOT / 'knowledge/city/measured_source_parcels.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'measured': report,
                               'note': 'Frontage segments are runs of occupied columns along the outer '
                                       'street envelope of each source build. Floor heights of the real '
                                       'buildings are 3-4 blocks, so these numbers are comparable with '
                                       'the parcel ranges in paris_1900_city_v0.1.json.'},
                              ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('\nwrote', out)


if __name__ == '__main__':
    main()
