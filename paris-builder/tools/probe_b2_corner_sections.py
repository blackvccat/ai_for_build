"""Second probe: cross-sections through the SW corner and the dome of building2.

Read-only. Prints y-rows for chosen vertical sections plus per-y floor maps of
the corner region, so crop boxes can be fixed without touching the source.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import numpy as np
from paris_builder.schematic import load_schematic
from paris_builder.source_decomposition import state_grid

SOURCE = ROOT.parent / '巴黎建筑素材' / '巴黎建筑素材2.schem'


def section_zy(grid, x, z0, z1, y0, y1):
    """z-y section at fixed x: z across, y down (top row = y1-1)."""
    lines = [f'== z-y section x={x}  (z {z0}..{z1-1} across, y {y1-1} down to {y0}) ==']
    lines.append('     ' + ''.join(str(z % 10) for z in range(z0, z1)))
    for y in range(y1 - 1, y0 - 1, -1):
        row = ''.join('#' if not str(grid[y, z, x]).startswith('minecraft:air') else '.'
                      for z in range(z0, z1))
        lines.append(f'y={y:3d} {row}')
    return '\n'.join(lines)


def section_xy(grid, z, x0, x1, y0, y1):
    lines = [f'== x-y section z={z}  (x {x0}..{x1-1} across, y {y1-1} down to {y0}) ==']
    lines.append('     ' + ''.join(str(x % 10) for x in range(x0, x1)))
    for y in range(y1 - 1, y0 - 1, -1):
        row = ''.join('#' if not str(grid[y, z, x]).startswith('minecraft:air') else '.'
                      for x in range(x0, x1))
        lines.append(f'y={y:3d} {row}')
    return '\n'.join(lines)


def floor_map(grid, y, x0, x1, z0, z1):
    lines = [f'== floor y={y} (x {x0}..{x1-1} across, z {z0}..{z1-1} down) ==']
    lines.append('     ' + ''.join(str(x % 10) for x in range(x0, x1)))
    for z in range(z0, z1):
        row = ''.join('#' if not str(grid[y, z, x]).startswith('minecraft:air') else '.'
                      for x in range(x0, x1))
        lines.append(f'z={z:3d} {row}')
    return '\n'.join(lines)


def main():
    data = load_schematic(SOURCE)
    grid = state_grid(data)
    print('--- SW corner: z-y sections through the curve (x = 5, 7, 9, 11) ---')
    for x in (5, 7, 9, 11):
        print(section_zy(grid, x, 78, 96, 0, 61))
    print('\n--- SW corner: x-y sections (z = 84, 88, 92) ---')
    for z in (84, 88, 92):
        print(section_xy(grid, z, 0, 27, 0, 61))
    print('\n--- corner floors: maps at window-band heights ---')
    for y in (4, 10, 16, 22, 28, 34, 40, 46, 52):
        print(floor_map(grid, y, 0, 27, 78, 96))
    print('\n--- dome: z-y sections (x = 4, 7, 10, 13) ---')
    for x in (4, 7, 10, 13):
        print(section_zy(grid, x, 36, 62, 30, 61))
    print('\n--- dome: x-y sections (z = 41, 47, 54) ---')
    for z in (41, 47, 54):
        print(section_xy(grid, z, 0, 27, 30, 61))
    print('\n--- +z facade: x-y section at z=92, full width ---')
    print(section_xy(grid, 92, 0, 59, 0, 61))


if __name__ == '__main__':
    main()
