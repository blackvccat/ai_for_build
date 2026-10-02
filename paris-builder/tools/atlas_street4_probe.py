"""Probe street4 (巴黎民居街区4[斜面建筑]) geometry: footprints, prow tip, corner tower.

Read-only diagnostic for the st4-* decomposition. Prints ASCII maps so the wedge
(prow) plan, rounded corner building and shopfront locations can be pinned down
without touching the source.
"""
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import numpy as np
from paris_builder.schematic import load_schematic
from paris_builder.source_decomposition import state_grid

SOURCE = ROOT.parent / '巴黎建筑素材' / '巴黎民居街区4[斜面建筑].schem'


def ascii_map(mask, x0, z0, x1, z1, step=1):
    """mask[z, x]; print a z-row/x-column map, x across, z down, with rulers."""
    lines = ['     ' + ''.join(str((x // 10) % 10) for x in range(x0, x1, step)),
             '     ' + ''.join(str(x % 10) for x in range(x0, x1, step))]
    for z in range(z0, z1, step):
        row = ''.join('#' if mask[z, x] else '.' for x in range(x0, x1, step))
        lines.append(f'z={z:3d} {row}')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ys', type=int, nargs='*', default=None)
    args = parser.parse_args()
    data = load_schematic(SOURCE)
    grid = state_grid(data)
    nonair = np.array([not str(s).startswith('minecraft:air') for s in grid.ravel()]).reshape(grid.shape)
    h, d, w = nonair.shape
    print(f'dimensions w×h×d = {w}×{h}×{d}  data_version={data.data_version}  offset={data.offset}')
    print(f'nonair total = {int(nonair.sum())}')

    # column top-y map
    top = np.full((d, w), -1, dtype=int)
    for y in range(h - 1, -1, -1):
        fill = nonair[y] & (top < 0)
        top[fill] = y
    print('\ncolumn top-y map (z rows, x cols, coarse every 2):')
    for z in range(0, d, 2):
        row = ' '.join(f'{top[z, x]:2d}' for x in range(0, w, 2))
        print(f'z={z:3d} {row}')

    ys = args.ys or [0, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 31, 33, 35, 37, 39, 41, 43, 45, 47]
    for y in ys:
        if y >= h:
            continue
        layer = nonair[y]
        if not layer.any():
            continue
        print(f'\nfootprint y={y}  (x across, z down)')
        print(ascii_map(layer, 0, 0, w, d))


if __name__ == '__main__':
    main()
