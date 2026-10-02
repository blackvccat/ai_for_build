"""Probe round 5: unrolled wedge elevations, balcony z=2 plane, roof profiles."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import numpy as np
from paris_builder.schematic import load_schematic, base_block
from paris_builder.source_decomposition import state_grid

SOURCE = ROOT.parent / '巴黎建筑素材' / '巴黎民居街区4[斜面建筑].schem'

CH = {'iron_door': 'D', 'mangrove_door': 'M', 'birch_door': 'b', 'dark_oak_door': 'k',
      'white_stained_glass_pane': 'g', 'white_stained_glass': 'G', 'glass': 'G',
      'red_stained_glass': 'R', 'iron_bars': 'i', 'birch_trapdoor': 't',
      'dark_oak_trapdoor': 'T', 'warped_trapdoor': 'W', 'iron_trapdoor': 'I',
      'birch_fence': 'f', 'dark_oak_fence': 'F', 'sandstone_wall': '|',
      'diorite_wall': '|', 'polished_deepslate_wall': '=', 'deepslate_brick_wall': '=',
      'lever': 'v', 'chain': 'c', 'flower_pot': 'p', 'snow': 's',
      'dead_bubble_coral_fan': '*', 'dead_brain_coral_fan': '*', 'white_concrete': 'w',
      'warped_slab': 'W', 'birch_wall_sign': 'S'}


def lab(s):
    if s.startswith('minecraft:air'):
        return '.'
    return CH.get(base_block(s).split(':')[1], '#')


def main():
    data = load_schematic(SOURCE)
    grid = state_grid(data)
    h, d, w = grid.shape
    nonair = np.array([not str(s).startswith('minecraft:air') for s in grid.ravel()]).reshape(grid.shape)

    print('=== A. BAR west building z=2 plane elevation (projected balconettes), x 17-50, y 7-33 ===')
    lines = ['      ' + ''.join(str((x // 10) % 10) for x in range(17, 50)),
             '      ' + ''.join(str(x % 10) for x in range(17, 50))]
    for y in range(33, 6, -1):
        row = ''.join(lab(str(grid[y, 2, x])) for x in range(17, 50))
        lines.append(f'y={y:3d} {row}')
    print('\n'.join(lines))

    print('\n=== B. WEDGE SW wall unrolled (outer face at min-x cluster), z 30-118, y 0-34 ===')
    sw = {}
    for z in range(30, 119):
        xs = [x for x in range(40, 75) if nonair[0:34, z, x].any()]
        sw[z] = min(xs) if xs else None
    lines = ['      ' + ''.join(str((z // 10) % 10) for z in range(30, 119)),
             '      ' + ''.join(str(z % 10) for z in range(30, 119))]
    for y in range(33, -1, -1):
        row = ''
        for z in range(30, 119):
            x = sw[z]
            row += ' ' if x is None else lab(str(grid[y, z, x]))
        lines.append(f'y={y:3d} {row}')
    print('\n'.join(lines))
    print('SW wall x per z: ' + ' '.join(f'{z}:{sw[z]}' for z in range(30, 119) if z % 2 == 0))

    print('\n=== C. WEDGE NE wall unrolled (outer face at max-x cluster), z 30-118, y 0-34 ===')
    ne = {}
    for z in range(30, 119):
        xs = [x for x in range(70, 105) if nonair[0:34, z, x].any()]
        ne[z] = max(xs) if xs else None
    lines = ['      ' + ''.join(str((z // 10) % 10) for z in range(30, 119)),
             '      ' + ''.join(str(z % 10) for z in range(30, 119))]
    for y in range(33, -1, -1):
        row = ''
        for z in range(30, 119):
            x = ne[z]
            row += ' ' if x is None else lab(str(grid[y, z, x]))
        lines.append(f'y={y:3d} {row}')
    print('\n'.join(lines))
    print('NE wall x per z: ' + ' '.join(f'{z}:{ne[z]}' for z in range(30, 119) if z % 2 == 0))

    print('\n=== D. WEDGE transverse roof sections: x-rows at fixed z, y 28-47 ===')
    for z in (40, 52, 65, 78, 92, 106):
        print(f'-- z={z} (x across, y down; #=any block)')
        lines = ['      ' + ''.join(str((x // 10) % 10) for x in range(45, 100)),
                 '      ' + ''.join(str(x % 10) for x in range(45, 100))]
        for y in range(47, 27, -1):
            row = ''.join(lab(str(grid[y, z, x])) for x in range(45, 100))
            lines.append(f'y={y:3d} {row}')
        print('\n'.join(lines))

    print('\n=== E. BAR west roof longitudinal strip x 22-24 (z across, y down) ===')
    lines = ['      ' + ''.join(str(z % 10) for z in range(0, 28))]
    for y in range(45, 27, -1):
        row = ''
        for z in range(0, 28):
            cells = [lab(str(grid[y, z, x])) for x in (22, 23, 24)]
            row += next((c for c in cells if c != '.'), '.')
        lines.append(f'y={y:3d} {row}')
    print('\n'.join(lines))

    print('\n=== F. lower dormer z position (bar west, GG glass y31-33): exact cells x 19-26 ===')
    for y in range(29, 36):
        for z in range(1, 12):
            cells = ' '.join(f'{x}:{lab(str(grid[y, z, x]))}' for x in range(19, 27)
                             if not str(grid[y, z, x]).startswith('minecraft:air'))
            if cells:
                print(f'y={y} z={z:2d}: {cells}')


if __name__ == '__main__':
    main()
