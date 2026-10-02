"""Probe building2 corner geometry: footprint maps, height profile, dome location.

Read-only diagnostic for the b2-corner-* decomposition. Prints ASCII maps so the
corner arc, dome and roof cresting can be located without touching the source.
"""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import numpy as np
from paris_builder.schematic import load_schematic
from paris_builder.source_decomposition import state_grid

SOURCE = ROOT.parent / '巴黎建筑素材' / '巴黎建筑素材2.schem'


def ascii_map(mask, x0, z0, x1, z1, step=1):
    """mask[y,z,x]; print a z-row/x-column map, x across, z down, with rulers."""
    lines = []
    header = '    ' + ''.join(str((x // 10) % 10) if x % 10 == 0 or True else ' ' for x in range(x0, x1, step))
    lines.append(header)
    lines.append('    ' + ''.join(str(x % 10) for x in range(x0, x1, step)))
    for z in range(z0, z1, step):
        row = ''.join('#' if mask[z, x] else '.' for x in range(x0, x1, step))
        lines.append(f'{z:3d} {row}')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', type=Path)
    args = parser.parse_args()
    data = load_schematic(SOURCE)
    grid = state_grid(data)
    nonair = np.array([not str(s).startswith('minecraft:air') for s in grid.ravel()]).reshape(grid.shape)
    h, d, w = nonair.shape
    print(f'dimensions w×h×d = {w}×{h}×{d}  data_version={data.data_version}  offset={data.offset}')
    print(f'nonair total = {int(nonair.sum())}')

    # Column top-y map for the x_min end: where does the roof/dome reach?
    report = {'dimensions_whd': [w, h, d]}
    top = np.full((d, w), -1, dtype=int)
    for y in range(h - 1, -1, -1):
        fill = nonair[y] & (top < 0)
        top[fill] = y
    xmax_probe = min(26, w)
    print(f'\ncolumn top-y, x 0..{xmax_probe}, all z (values are max non-air y):')
    for z in range(d):
        row = ' '.join(f'{top[z, x]:3d}' for x in range(0, xmax_probe))
        if top[z, :xmax_probe].max() >= 0:
            print(f'z={z:3d} {row}')

    # Footprint slices at key heights over the same region
    for y in (2, 8, 14, 20, 26, 32, 38, 44, 50, 56, 60, 64, 68, 72):
        if y >= h:
            continue
        layer = nonair[y]
        if not layer[:, :xmax_probe].any():
            continue
        print(f'\nfootprint y={y}  (x 0..{xmax_probe} across, z down)')
        print(ascii_map(layer, 0, 0, xmax_probe, d))

    # Highest blocks anywhere: dome/cresting candidates
    ys, zs, xs = np.nonzero(nonair)
    ymax = int(ys.max())
    print(f'\nglobal max y = {ymax}; columns reaching y>= {ymax - 6}:')
    high = {}
    for y, z, x in zip(ys, zs, xs):
        if y >= ymax - 6:
            high.setdefault((int(x), int(z)), int(y))
    for (x, z), y in sorted(high.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f'  x={x} z={z} top_y={y} state={grid[y, z, x]}')

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
