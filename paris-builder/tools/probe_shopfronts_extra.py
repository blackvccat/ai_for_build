"""Targeted probe for shopfronts-extra decomposition (街区6 ground floor bands, 街区7 chamfer/wings).

Read-only. Prints per-column and per-depth state signatures so bboxes for
decompose_shopfronts_extra.py can be chosen from measurements.

Usage (from paris-builder/, PYTHONPATH=src):
    python -X utf8 tools/probe_shopfronts_extra.py st6-band --x0 17 --x1 42
    python -X utf8 tools/probe_shopfronts_extra.py st6-modern --x0 59 --x1 77
    python -X utf8 tools/probe_shopfronts_extra.py st7-chamfer
    python -X utf8 tools/probe_shopfronts_extra.py st7-wing
"""
from collections import Counter
from pathlib import Path
import argparse
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from paris_builder.schematic import load_schematic, AIR_BLOCKS, base_block
from paris_builder.source_decomposition import state_grid

SOURCES = {
    'st6': ROOT.parent / '巴黎建筑素材' / '巴黎民居街区6.schem',
    'st7': ROOT.parent / '巴黎建筑素材' / '巴黎民居街区7.schem',
}


def short(state):
    return base_block(str(state)).replace('minecraft:', '')


def per_x_summary(grid, y0, y1, z0, z1, x0, x1):
    """Top base blocks per x column within a y/z window."""
    for x in range(x0, x1):
        vals = [short(v) for v in grid[y0:y1, z0:z1, x].ravel()
                if short(v) not in AIR_BLOCKS]
        counts = Counter(vals)
        top = ', '.join(f'{k}x{v}' for k, v in counts.most_common(8))
        print(f'  x={x:3d}: {top}')


def per_z_summary(grid, y0, y1, x0, x1, z0, z1):
    for z in range(z0, z1):
        vals = [short(v) for v in grid[y0:y1, z, x0:x1].ravel()
                if short(v) not in AIR_BLOCKS]
        counts = Counter(vals)
        top = ', '.join(f'{k}x{v}' for k, v in counts.most_common(10))
        print(f'  z={z:3d}: {top}')


def per_y_summary(grid, x0, x1, z0, z1, y0, y1):
    for y in range(y0, y1):
        vals = [short(v) for v in grid[y, z0:z1, x0:x1].ravel()
                if short(v) not in AIR_BLOCKS]
        counts = Counter(vals)
        top = ', '.join(f'{k}x{v}' for k, v in counts.most_common(10))
        print(f'  y={y:3d}: {top}')


def plan_view(grid, y, x0, x1, z0, z1):
    """ASCII plan at one height: first letter per block."""
    print(f'  plan y={y}, rows z={z0}..{z1-1}, cols x={x0}..{x1-1}')
    print('      ' + ''.join(str(x % 10) for x in range(x0, x1)))
    for z in range(z0, z1):
        row = []
        for x in range(x0, x1):
            name = short(grid[y, z, x])
            row.append(' ' if name in AIR_BLOCKS else name[0])
        print(f'  z={z:3d}: ' + ''.join(row))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('st6-band', 'st6-modern', 'st7-chamfer', 'st7-wing'))
    parser.add_argument('--x0', type=int, default=0)
    parser.add_argument('--x1', type=int, default=77)
    parser.add_argument('--y0', type=int, default=0)
    parser.add_argument('--y1', type=int, default=14)
    parser.add_argument('--z0', type=int, default=15)
    parser.add_argument('--z1', type=int, default=25)
    args = parser.parse_args()
    if args.mode.startswith('st6'):
        data = load_schematic(SOURCES['st6'])
        grid = state_grid(data)
        print(f'== st6 WHD={data.width}x{data.height}x{data.length} mode={args.mode}')
        print('-- per-x ground-floor signature:')
        per_x_summary(grid, args.y0, args.y1, args.z0, args.z1, args.x0, args.x1)
        print('-- per-z depth signature over chosen x window:')
        per_z_summary(grid, args.y0, args.y1, args.x0, args.x1, args.z0, args.z1)
        print('-- per-y signature over chosen x/z window:')
        per_y_summary(grid, args.x0, args.x1, args.z0, args.z1, args.y0, args.y1)
        for y in (0, 4, 9):
            plan_view(grid, y, args.x0, args.x1, args.z0, args.z1)
    elif args.mode == 'st7-chamfer':
        data = load_schematic(SOURCES['st7'])
        grid = state_grid(data)
        print(f'== st7 WHD={data.width}x{data.height}x{data.length} chamfer probe x 60..100 z 40..70 y 0..14')
        print('-- per-y signature:')
        per_y_summary(grid, 60, 100, 40, 70, 0, 14)
        for y in (0, 1, 2, 3, 4, 5, 9):
            plan_view(grid, y, 60, 100, 40, 70)
        print('-- per-z depth signature x 70..90 y 0..12:')
        per_z_summary(grid, 0, 12, 70, 90, 40, 70)
    else:
        data = load_schematic(SOURCES['st7'])
        grid = state_grid(data)
        print(f'== st7 WHD={data.width}x{data.height}x{data.length} wing probe (west wing x 8..70)')
        print('-- per-y signature x 30..66 z 55..110 y 0..14:')
        per_y_summary(grid, 30, 66, 55, 110, 0, 14)
        for y in (0, 4):
            plan_view(grid, y, 30, 66, 55, 110)


if __name__ == '__main__':
    main()
