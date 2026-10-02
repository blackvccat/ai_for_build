"""Probe building6 (巴黎建筑素材6, B-class palace/hotel) geometry for element decomposition.

Read-only diagnostic for the b6-* atlas pieces. Prints ASCII footprint maps and
column dumps so the colonnade/arcade, window bays, end pavilions, court faces,
cornice, roof, dormers, entry and base can be pinned down without touching the source.

Usage (from paris-builder/, PYTHONPATH=src):
    python -X utf8 tools/atlas_b6_probe.py [--ys 0 5 10] [--region X0 Z0 X1 Z1]
    python -X utf8 tools/atlas_b6_probe.py --column X Z
    python -X utf8 tools/atlas_b6_probe.py --states SUBSTR [SUBSTR ...] [--ys ...]
"""
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import numpy as np
from paris_builder.schematic import load_schematic
from paris_builder.source_decomposition import state_grid

SOURCE = ROOT.parent / '巴黎建筑素材' / '巴黎建筑素材6.schem'


def ascii_map(mask, x0, z0, x1, z1, step=1):
    lines = ['     ' + ''.join(str((x // 10) % 10) for x in range(x0, x1, step)),
             '     ' + ''.join(str(x % 10) for x in range(x0, x1, step))]
    for z in range(z0, z1, step):
        row = ''.join('#' if mask[z, x] else '.' for x in range(x0, x1, step))
        lines.append(f'z={z:3d} {row}')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ys', type=int, nargs='*', default=None)
    parser.add_argument('--region', type=int, nargs=4, default=None, metavar=('X0', 'Z0', 'X1', 'Z1'))
    parser.add_argument('--step', type=int, default=1)
    parser.add_argument('--column', type=int, nargs=2, default=None, metavar=('X', 'Z'))
    parser.add_argument('--states', nargs='*', default=None,
                        help='only mark cells whose state contains all given substrings')
    args = parser.parse_args()
    data = load_schematic(SOURCE)
    grid = state_grid(data)
    nonair = np.array([not str(s).startswith('minecraft:air') for s in grid.ravel()]).reshape(grid.shape)
    h, d, w = nonair.shape
    print(f'dimensions w×h×d = {w}×{h}×{d}  data_version={data.data_version}  offset={data.offset}')
    print(f'nonair total = {int(nonair.sum())}')

    if args.column is not None:
        x, z = args.column
        print(f'\ncolumn ({x},{z}) bottom-up:')
        for y in range(h):
            if nonair[y, z, x]:
                print(f'y={y:3d}  {grid[y, z, x]}')
        return

    x0, z0, x1, z1 = args.region if args.region else (0, 0, w, d)
    step = args.step
    mask = nonair
    if args.states:
        wanted = args.states
        flat = grid.ravel()
        hit = np.array([all(t in str(s) for t in wanted) for s in flat]).reshape(grid.shape)
        mask = hit
        print(f'state filter: {wanted} -> {int(hit.sum())} cells')
    ys = args.ys if args.ys is not None else list(range(0, h, 2))
    for y in ys:
        if y >= h:
            continue
        layer = mask[y, z0:z1, x0:x1]
        if not layer.any():
            continue
        print(f'\nfootprint y={y}  (x across, z down)')
        print(ascii_map(mask[y], x0, z0, x1, z1, step))


if __name__ == '__main__':
    main()
