"""Detailed probe of street4 prow tip, corner chamfer, ground slope and shopfronts.

Read-only. Prints: (1) footprints of the prow-tip region at several heights,
(2) NE-corner chamfer of the corner building, (3) per-z wall y-ranges along the
wedge to expose the slope, (4) ground-floor block census along street faces.
"""
from pathlib import Path
import sys
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import numpy as np
from paris_builder.schematic import load_schematic, base_block
from paris_builder.source_decomposition import state_grid

SOURCE = ROOT.parent / '巴黎建筑素材' / '巴黎民居街区4[斜面建筑].schem'


def ascii_region(grid, y, x0, z0, x1, z1, labels=False):
    lines = ['     ' + ''.join(str((x // 10) % 10) for x in range(x0, x1)),
             '     ' + ''.join(str(x % 10) for x in range(x0, x1))]
    for z in range(z0, z1):
        row = ''
        for x in range(x0, x1):
            s = str(grid[y, z, x])
            if s.startswith('minecraft:air'):
                row += '.'
            elif labels:
                b = base_block(s).split(':')[1]
                row += {'iron_door': 'D', 'oak_door': 'd', 'spruce_door': 'd', 'birch_door': 'd',
                        'dark_oak_door': 'd', 'jungle_door': 'd', 'acacia_door': 'd',
                        'warped_door': 'd', 'crimson_door': 'd', 'mangrove_door': 'd',
                        'white_stained_glass': 'g', 'glass': 'G'}.get(b, '#')
            else:
                row += '#'
        lines.append(f'z={z:3d} {row}')
    return '\n'.join(lines)


def main():
    data = load_schematic(SOURCE)
    grid = state_grid(data)
    h, d, w = grid.shape
    nonair = np.array([not str(s).startswith('minecraft:air') for s in grid.ravel()]).reshape(grid.shape)

    print('=== (1) PROW TIP region x40-95 z90-119 ===')
    for y in (0, 1, 2, 4, 6, 10, 14, 18, 22, 26, 30, 33, 36, 39, 42, 45):
        if not nonair[y, 90:119, 40:95].any():
            continue
        print(f'\n-- y={y} --')
        print(ascii_region(grid, y, 40, 90, 95, 119))

    print('\n=== (2) CORNER building NE corner x90-111 z0-25 ===')
    for y in (0, 1, 2, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 25, 29, 33, 36, 39, 42):
        if not nonair[y, 0:25, 90:111].any():
            continue
        print(f'\n-- y={y} --')
        print(ascii_region(grid, y, 90, 0, 111, 25))

    print('\n=== (3) WEDGE wall lines: per-z x-range and y-range (z 30-119) ===')
    for z in range(30, 119):
        cols = [(x, int(np.nonzero(nonair[:, z, x])[0].min()), int(np.nonzero(nonair[:, z, x])[0].max()))
                for x in range(w) if nonair[:, z, x].any()]
        if not cols:
            continue
        xs = [c[0] for c in cols]
        mins = [c[1] for c in cols]
        maxs = [c[2] for c in cols]
        print(f'z={z:3d} x {min(xs)}..{max(xs)}  ymin {min(mins)}..{max(mins)}  ymax {min(maxs)}..{max(maxs)}')

    print('\n=== (4a) ground-floor census y0-6 along bar north face (z 1-6, x 0-108) ===')
    cnt = Counter()
    for y in range(0, 7):
        for z in range(1, 7):
            for x in range(0, 108):
                s = str(grid[y, z, x])
                if not s.startswith('minecraft:air'):
                    cnt[s] += 1
    for s, n in cnt.most_common(60):
        print(f'{n:5d}  {s}')

    print('\n=== (4b) shopfront color scan: non-stone blocks at y1-5 in wedge walls zone ===')
    interesting = Counter()
    for y in range(0, 7):
        for z in range(30, 119):
            for x in range(40, 100):
                s = str(grid[y, z, x])
                b = base_block(s)
                if s.startswith('minecraft:air'):
                    continue
                if any(k in b for k in ('wool', 'terracotta', 'concrete', 'glazed', 'glass', 'door',
                                        'sign', 'banner', 'carpet', 'awning', 'fence', 'gate', 'trapdoor',
                                        'ladder', 'vine', 'glow', 'lantern', 'chain', 'leaves')):
                    interesting[s] += 1
    for s, n in interesting.most_common(80):
        print(f'{n:5d}  {s}')


if __name__ == '__main__':
    main()
