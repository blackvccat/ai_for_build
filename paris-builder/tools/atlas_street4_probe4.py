"""Probe round 4: facade rhythms, balcony bands, dormers, chimney makeup, slope check."""
from pathlib import Path
import sys
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import numpy as np
from paris_builder.schematic import load_schematic, base_block
from paris_builder.source_decomposition import state_grid

SOURCE = ROOT.parent / '巴黎建筑素材' / '巴黎民居街区4[斜面建筑].schem'


def elev(grid, x0, x1, y0, y1, z, title):
    """Elevation at fixed z (looking at north face): x across, y down."""
    print(title)
    lines = ['     ' + ''.join(str((x // 10) % 10) for x in range(x0, x1)),
             '     ' + ''.join(str(x % 10) for x in range(x0, x1))]
    for y in range(y1 - 1, y0 - 1, -1):
        row = ''
        for x in range(x0, x1):
            s = str(grid[y, z, x])
            b = base_block(s).split(':')[1]
            ch = '.' if s.startswith('minecraft:air') else {
                'iron_door': 'D', 'mangrove_door': 'M', 'birch_door': 'b', 'dark_oak_door': 'k',
                'white_stained_glass_pane': 'g', 'white_stained_glass': 'G', 'glass': 'G',
                'red_stained_glass': 'R', 'iron_bars': 'i', 'birch_trapdoor': 't',
                'dark_oak_trapdoor': 'T', 'warped_trapdoor': 'W', 'iron_trapdoor': 'I',
                'birch_fence': 'f', 'dark_oak_fence': 'F', 'sandstone_wall': '|',
                'diorite_wall': '|', 'polished_deepslate_wall': '=', 'deepslate_brick_wall': '=',
                'lever': 'v', 'chain': 'c', 'flower_pot': 'p', 'snow': 's',
                'dead_bubble_coral_fan': '*', 'dead_brain_coral_fan': '*',
            }.get(b, '#')
            row += ch
        lines.append(f'y={y:3d} {row}')
    print('\n'.join(lines))


def main():
    data = load_schematic(SOURCE)
    grid = state_grid(data)
    h, d, w = grid.shape

    elev(grid, 0, 108, 0, 42, 3, '=== A. BAR north face full elevation at z=3 (x across, y down) ===')

    # corner building east face elevation at x=103 (z across)
    print('\n=== B. CORNER building east face elevation at x=103 (z across, y down) ===')
    lines = ['     ' + ''.join(str(z % 10) for z in range(0, 40))]
    for y in range(40, -1, -1):
        row = ''
        for z in range(0, 40):
            s = str(grid[y, z, 103])
            b = base_block(s).split(':')[1]
            ch = '.' if s.startswith('minecraft:air') else {
                'iron_door': 'D', 'mangrove_door': 'M', 'birch_door': 'b',
                'white_stained_glass_pane': 'g', 'white_stained_glass': 'G',
                'iron_bars': 'i', 'birch_trapdoor': 't', 'dark_oak_trapdoor': 'T',
                'iron_trapdoor': 'I', 'birch_fence': 'f', 'sandstone_wall': '|',
                'diorite_wall': '|', 'lever': 'v', 'chain': 'c', 'flower_pot': 'p',
            }.get(b, '#')
            row += ch
        lines.append(f'y={y:3d} {row}')
    print('\n'.join(lines))

    print('\n=== C. balcony-band scan: rows of iron_bars/fence/trapdoor at facade-adjacent cells ===')
    # bar north face: scan z=3..6 for y rows with many bars/fences
    for y in range(6, 32):
        cnt = Counter()
        for x in range(0, 108):
            for z in range(2, 8):
                b = base_block(str(grid[y, z, x]))
                if b in ('minecraft:iron_bars', 'minecraft:birch_fence', 'minecraft:dark_oak_fence',
                         'minecraft:birch_trapdoor', 'minecraft:dark_oak_trapdoor', 'minecraft:lever',
                         'minecraft:sandstone_wall', 'minecraft:chain'):
                    cnt[b.split(':')[1]] += 1
        if cnt:
            print(f'bar-front y={y:2d}: {dict(cnt)}')

    print('\n=== D. chimney stack dumps ===')
    for (x, z) in [(27, 10), (32, 11), (85, 48), (71, 89)]:
        col = [(y, str(grid[y, z, x])) for y in range(38, h) if not str(grid[y, z, x]).startswith('minecraft:air')]
        print(f'chimney column x={x} z={z}:')
        for y, s in col:
            print(f'   y={y:2d} {s}')

    print('\n=== E. BAR west mansard front slope: find dormer z/y (x 19-47) ===')
    for y in range(30, 44):
        row = ''
        for x in range(18, 50):
            best = '.'
            for z in range(2, 12):
                s = str(grid[y, z, x])
                if not s.startswith('minecraft:air'):
                    b = base_block(s).split(':')[1]
                    ch = {'iron_door': 'D', 'white_stained_glass_pane': 'g', 'white_stained_glass': 'G',
                          'iron_bars': 'i', 'birch_trapdoor': 't', 'iron_trapdoor': 'I',
                          'diorite_wall': '|', 'sandstone_wall': '|', 'dark_oak_trapdoor': 'T',
                          'snow': 's', 'lever': 'v'}.get(b, '#')
                    if best == '.' or ch != '#':
                        best = ch
            row += best
        print(f'y={y:2d} {row}   (x 18-49, any z 2-11)')

    print('\n=== F. slope check: shop floor bottom-y along wedge facades ===')
    # for each z, find min y of the SW wall cluster (first nonair x-run from min x) at y<10
    for z in range(30, 119, 2):
        xs = [x for x in range(w) if any(not str(grid[y, z, x]).startswith('minecraft:air') for y in range(0, 10))]
        if not xs:
            continue
        groups = [[xs[0]]]
        for x in xs[1:]:
            if x - groups[-1][-1] <= 2:
                groups[-1].append(x)
            else:
                groups.append([x])
        desc = []
        for g in groups:
            miny = min(y for x in g for y in range(0, 10)
                       if not str(grid[y, z, x]).startswith('minecraft:air'))
            desc.append(f'x{g[0]}-{g[-1]}@y{miny}')
        print(f'z={z:3d}: ' + '  '.join(desc))

    print('\n=== G. corner building cap: light well + arc at y 31-46 (x 76-109, z 0-28) ===')
    for y in (31, 33, 35, 37, 39, 41, 43, 45):
        print(f'-- y={y}')
        lines = ['      ' + ''.join(str((x // 10) % 10) for x in range(76, 110)),
                 '      ' + ''.join(str(x % 10) for x in range(76, 110))]
        for z in range(0, 28):
            row = ''
            for x in range(76, 110):
                s = str(grid[y, z, x])
                b = base_block(s).split(':')[1]
                ch = '.' if s.startswith('minecraft:air') else {
                    'iron_door': 'D', 'white_stained_glass_pane': 'g', 'iron_bars': 'i',
                    'birch_trapdoor': 't', 'iron_trapdoor': 'I', 'diorite_wall': '|',
                    'sandstone_wall': '|', 'chain': 'c', 'flower_pot': 'p', 'snow': 's',
                    'dark_oak_trapdoor': 'T', 'lever': 'v'}.get(b, '#')
                row += ch
            lines.append(f'z={z:3d} {row}')
        print('\n'.join(lines))


if __name__ == '__main__':
    main()
