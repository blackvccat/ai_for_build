"""Probe round 3: locate street4 shops, low fragments, chimneys, dormers, balcony bands."""
from pathlib import Path
import sys
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import numpy as np
from paris_builder.schematic import load_schematic, base_block
from paris_builder.source_decomposition import state_grid

SOURCE = ROOT.parent / '巴黎建筑素材' / '巴黎民居街区4[斜面建筑].schem'


def label(s):
    b = base_block(s).split(':')[1]
    if s.startswith('minecraft:air'):
        return '.'
    return {'iron_door': 'D', 'mangrove_door': 'M', 'birch_door': 'b', 'oak_door': 'd', 'spruce_door': 'd',
            'dark_oak_door': 'k', 'jungle_door': 'j', 'warped_door': 'w',
            'white_stained_glass_pane': 'g', 'white_stained_glass': 'G', 'glass': 'G',
            'red_stained_glass': 'R', 'warped_trapdoor': 'W', 'birch_trapdoor': 't',
            'dark_oak_trapdoor': 'T', 'iron_trapdoor': 'I', 'birch_fence': 'f', 'dark_oak_fence': 'F',
            'birch_wall_sign': 'S', 'ladder': 'L', 'white_concrete': 'c', 'gray_wool': 'y',
            'black_wool': 'K', 'white_shulker_box': 'u', 'smooth_sandstone': '#', 'diorite': '#',
            'cracked_deepslate_bricks': '=', 'sandstone_wall': '|', 'polished_deepslate_wall': '|',
            'create:cut_calcite_wall': 'C'}.get(b, '#')


def strip_map(grid, y0, y1, z0, z1, x0, x1, axis='x'):
    """Plan map of the most 'interesting' block per column in [y0,y1)."""
    lines = ['     ' + ''.join(str((i // 10) % 10) for i in range(x0, x1)),
             '     ' + ''.join(str(i % 10) for i in range(x0, x1))]
    prio = 'DMbdjkwgGRWtTIfSLc yKu'
    for z in range(z0, z1):
        row = ''
        for x in range(x0, x1):
            best = '.'
            for y in range(y0, y1):
                ch = label(str(grid[y, z, x]))
                if ch == '.':
                    continue
                if best == '.' or (prio.find(ch) >= 0 and prio.find(ch) < prio.find(best)):
                    best = ch
            row += best
        lines.append(f'z={z:3d} {row}')
    return '\n'.join(lines)


def main():
    data = load_schematic(SOURCE)
    grid = state_grid(data)
    h, d, w = grid.shape

    print('=== A. BAR north face ground floor y0-8, z0-8, x0-108 ===')
    print(strip_map(grid, 0, 8, 0, 8, 0, 108))

    print('\n=== B. BAR north face ground floor y0-8, extended street z0-12 ===')
    for y in range(0, 8):
        print(f'-- y={y}')
        print(strip_map(grid, y, y + 1, 0, 12, 0, 108))

    print('\n=== C. WEDGE SW facade shops: vertical slices at z where warped_trapdoor/door/glass appear y0-7 ===')
    # find shop z-positions on SW wall (west cluster) and NE wall (east cluster)
    for side, xr in (('SW', range(40, 66)), ('NE', range(76, 100))):
        hits = defaultdict(list)
        for z in range(28, 119):
            for x in xr:
                for y in range(0, 8):
                    b = base_block(str(grid[y, z, x]))
                    if any(k in b for k in ('trapdoor', 'door', 'glass', 'fence', 'sign', 'shulker', 'wool', 'concrete')):
                        hits[z].append((x, y, b))
        print(f'-- {side} wall: z with shop-ish blocks y0-7:')
        zs = sorted(hits)
        # group consecutive z
        groups = []
        for z in zs:
            if groups and z - groups[-1][-1] <= 1:
                groups[-1].append(z)
            else:
                groups.append([z])
        for g in groups:
            kinds = Counter(b for z in g for _, _, b in hits[z])
            print(f'  z {g[0]}..{g[-1]}: {dict(kinds.most_common(12))}')

    print('\n=== D. low fragments vertical dumps ===')
    for (x, z) in [(72, 50), (72, 52), (72, 54), (58, 104), (76, 110), (74, 116), (74, 118), (81, 60), (81, 80)]:
        col = [(y, str(grid[y, z, x])) for y in range(h) if not str(grid[y, z, x]).startswith('minecraft:air')]
        if col:
            print(f'column x={x} z={z}:')
            for y, s in col:
                print(f'   y={y:2d} {s}')

    print('\n=== E. chimneys: columns with top-y>=46 ===')
    nonair = np.array([not str(s).startswith('minecraft:air') for s in grid.ravel()]).reshape(grid.shape)
    tops = {}
    for z in range(d):
        for x in range(w):
            ys = np.nonzero(nonair[:, z, x])[0]
            if len(ys) and ys.max() >= 46:
                tops[(x, z)] = int(ys.max())
    for (x, z), ty in sorted(tops.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        print(f'  x={x:3d} z={z:3d} top_y={ty} top_state={grid[ty, z, x]}')

    print('\n=== F. dormer scan on wedge slopes: white-ish blocks at y32-42 outside wall lines ===')
    hits = defaultdict(set)
    for z in range(28, 119):
        for x in range(40, 100):
            for y in range(31, 45):
                b = base_block(str(grid[y, z, x]))
                if any(k in b for k in ('diorite', 'iron_door', 'glass', 'andesite', 'bone', 'white')):
                    hits[(x // 4 * 4, z)].add(b.split(':')[1])
    for (xq, z), bs in sorted(hits.items(), key=lambda kv: kv[0][1]):
        if 'iron_door' in bs or 'white_stained_glass' in bs:
            print(f'  x~{xq:3d} z={z:3d}: {sorted(bs)}')


if __name__ == '__main__':
    main()
