"""Probe building5/building7 (巴黎建筑素材5/7) geometry for the corner-chamfer decomposition.

Read-only diagnostic for the b5-*/b7-* atlas pieces. Prints ASCII footprint maps and
column dumps so the chamfered corner (b5: x~0,z~171 area; b7: both z_max corners),
b5 giant pilasters and b7 arched windows can be pinned down without touching the source.
"""
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import numpy as np
from paris_builder.schematic import load_schematic
from paris_builder.source_decomposition import state_grid

SOURCES = {
    'b5': ROOT.parent / '巴黎建筑素材' / '巴黎建筑素材5.schem',
    'b7': ROOT.parent / '巴黎建筑素材' / '巴黎建筑素材7.schem',
}


def ascii_map(mask, x0, z0, x1, z1, step=1):
    lines = ['     ' + ''.join(str((x // 10) % 10) for x in range(x0, x1, step)),
             '     ' + ''.join(str(x % 10) for x in range(x0, x1, step))]
    for z in range(z0, z1, step):
        row = ''.join('#' if mask[z, x] else '.' for x in range(x0, x1, step))
        lines.append(f'z={z:3d} {row}')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', choices=list(SOURCES))
    parser.add_argument('--ys', type=int, nargs='*', default=None)
    parser.add_argument('--region', type=int, nargs=4, default=None, metavar=('X0', 'Z0', 'X1', 'Z1'))
    parser.add_argument('--column', type=int, nargs=2, default=None, metavar=('X', 'Z'))
    parser.add_argument('--full', action='store_true', help='full-footprint maps coarse step 4')
    args = parser.parse_args()
    data = load_schematic(SOURCES[args.source])
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
    step = 1 if not args.full else 4
    ys = args.ys or [0, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 31, 33, 35, 37, 39, 41]
    for y in ys:
        if y >= h:
            continue
        layer = nonair[y, z0:z1, x0:x1]
        if not layer.any():
            continue
        print(f'\nfootprint y={y}  (x across, z down)')
        print(ascii_map(nonair[y], x0, z0, x1, z1, step))


if __name__ == '__main__':
    main()
