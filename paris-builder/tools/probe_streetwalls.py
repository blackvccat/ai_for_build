"""Street-wall (街区5/6/7) decomposition probe: locate shopfronts, window screens, cornices.

Read-only on sources. Prints per-face richness and per-column ground-floor signatures
so bboxes for decompose_streetwalls.py can be chosen from measurements.

Usage (from paris-builder/, PYTHONPATH=src):
    python -X utf8 tools/probe_streetwalls.py 5
    python -X utf8 tools/probe_streetwalls.py 5 --face zmin --y0 0 --y1 12 --axis x
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
    5: ('street5', ROOT.parent / '巴黎建筑素材' / '巴黎民居街区5.schem'),
    6: ('street6', ROOT.parent / '巴黎建筑素材' / '巴黎民居街区6.schem'),
    7: ('street7', ROOT.parent / '巴黎建筑素材' / '巴黎民居街区7.schem'),
}

KEYWORDS = ('door', 'glass', 'sign', 'banner', 'chain', 'lantern', 'trapdoor',
            'fence', 'wall', 'pane', 'stairs', 'slab', 'button', 'lever',
            'flower', 'coral', 'candle', 'shulker', 'head', 'item_frame')


def face_richness(grid):
    """State variety per vertical face, averaged over face cells (non-air only)."""
    h, d, w = grid.shape
    faces = {
        'zmin(-z north)': grid[:, 0, :],
        'zmax(+z south)': grid[:, d - 1, :],
        'xmin(-x west)': grid[:, :, 0],
        'xmax(+x east)': grid[:, :, w - 1],
    }
    for name, plane in faces.items():
        vals = [str(v) for v in plane.ravel() if base_block(str(v)) not in AIR_BLOCKS]
        counts = Counter(vals)
        decorated = sum(c for s, c in counts.items()
                        if any(k in base_block(s) for k in KEYWORDS))
        print(f'  {name}: nonair={len(vals)} states={len(counts)} decorated_cells={decorated}')


def column_signature(grid, face, y0, y1, axis):
    """Per-column top blocks on the given face within y range."""
    h, d, w = grid.shape
    if face == 'zmin':
        slab = grid[y0:y1, 0, :]
        plane = grid[y0:y1, :, :]
        face_axis = 'x'
        depth_axis = 'z'
    elif face == 'zmax':
        slab = grid[y0:y1, d - 1, :]
        plane = grid[y0:y1, :, :]
        face_axis = 'x'
        depth_axis = 'z'
    elif face == 'xmin':
        slab = grid[y0:y1, :, 0]
        plane = grid[y0:y1, :, :]
        face_axis = 'z'
        depth_axis = 'x'
    else:
        slab = grid[y0:y1, :, w - 1]
        plane = grid[y0:y1, :, :]
        face_axis = 'z'
        depth_axis = 'x'
    cols = slab.shape[1]
    for c in range(cols):
        vals = [str(v) for v in slab[:, c] if base_block(str(v)) not in AIR_BLOCKS]
        counts = Counter(base_block(v).replace('minecraft:', '') for v in vals)
        top = ', '.join(f'{k}x{v}' for k, v in counts.most_common(6))
        print(f'  {face_axis}={c:3d}: {top}')


def door_map(grid):
    """Bounding ranges of door cells grouped by (base, half) and coarse position."""
    doors = {}
    h, d, w = grid.shape
    for y, z, x in np.ndindex(grid.shape):
        name = base_block(str(grid[y, z, x]))
        if name.endswith('_door'):
            doors.setdefault(name, []).append((x, y, z))
    for name, pts in sorted(doors.items()):
        arr = np.array(pts)
        print(f'  {name}: n={len(pts)} x[{arr[:,0].min()}..{arr[:,0].max()}] '
              f'y[{arr[:,1].min()}..{arr[:,1].max()}] z[{arr[:,2].min()}..{arr[:,2].max()}]')
        # cluster by z then print per-z-slice x ranges at ground y
        y_min = arr[:, 1].min()
        ground = arr[arr[:, 1] <= y_min + 3]
        if len(ground):
            zs = sorted(set(ground[:, 2].tolist()))
            for z in zs[:14]:
                xs = sorted(ground[ground[:, 2] == z][:, 0].tolist())
                print(f'    ground z={z}: x runs {runs(xs)}')


def runs(xs):
    out, start, prev = [], None, None
    for x in xs:
        if start is None:
            start = prev = x
        elif x == prev + 1:
            prev = x
        else:
            out.append(f'{start}-{prev}' if prev > start else str(start))
            start = prev = x
    if start is not None:
        out.append(f'{start}-{prev}' if prev > start else str(start))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=int, choices=(5, 6, 7))
    parser.add_argument('--face', choices=('zmin', 'zmax', 'xmin', 'xmax'))
    parser.add_argument('--y0', type=int, default=0)
    parser.add_argument('--y1', type=int, default=12)
    parser.add_argument('--axis', default='x')
    args = parser.parse_args()
    sid, path = SOURCES[args.source]
    data = load_schematic(path)
    grid = state_grid(data)
    print(f'== {sid} {path.name} WHD={data.width}x{data.height}x{data.length}')
    print('-- face richness:')
    face_richness(grid)
    print('-- door map:')
    door_map(grid)
    if args.face:
        print(f'-- column signature face={args.face} y[{args.y0}..{args.y1}):')
        column_signature(grid, args.face, args.y0, args.y1, args.axis)


if __name__ == '__main__':
    main()
