"""Exploration probe for building1 (巴黎建筑素材1, civic/monumental) element decomposition.

Two modes (from paris-builder/, PYTHONPATH=src):
    python -X utf8 tools/atlas_building1_probe.py plan y0 [y1 ...]   # ASCII horizontal slices
    python -X utf8 tools/atlas_building1_probe.py crop <name> x0 y0 z0 x1 y1 z1 [--max-size 900]

plan: prints one ASCII map per height (x across, z down), classifying blocks into
wall/roof/window-door/ornament/air so corner pavilions, courtyard and the central
tower are visible. crop: renders a bbox to runs/TECHNIQUE-ATLAS-v0.1/probe_b1/<name>/.
Idempotent; read-only on the source.
"""
from pathlib import Path
import argparse
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from paris_builder.schematic import load_schematic, base_block, AIR_BLOCKS
from paris_builder.source_decomposition import crop as crop_grid, encode
from paris_builder.exporter import write_schematic
from paris_builder.preview3d import render_previews

SOURCE = ROOT.parent / '巴黎建筑素材' / '巴黎建筑素材1.schem'
OUT = ROOT / 'runs' / 'TECHNIQUE-ATLAS-v0.1' / 'probe_b1'

ROOF = ('deepslate', 'blackstone', 'basalt', 'gray_concrete', 'tuff', 'cobbled_deepslate',
        'deepslate_brick', 'deepslate_tile', 'polished_deepslate', 'polished_blackstone')
WINDOW = ('door', 'glass', 'pane', 'iron_bars')
STONE = ('wool', 'sandstone', 'diorite', 'andesite', 'quartz', 'bone', 'concrete', 'stone',
         'calcite', 'granite', 'mud', 'smooth')


def classify(name):
    if 'chain' in name or 'iron_chain' in name:
        return 'c'
    if any(k in name for k in ('trapdoor', 'fence', 'wall', 'button', 'lever', 'hook',
                               'pressure_plate', 'coral', 'lichen', 'slab', 'stairs')):
        return ':'
    if any(k in name for k in WINDOW):
        return 'W'
    if any(k in name for k in ROOF):
        return '#'
    if any(k in name for k in STONE):
        return 'O'
    return '?'


def plan(data, heights):
    grid = np.asarray(data.id_to_state, dtype=object)[data.volume]
    for y in heights:
        layer = grid[y]
        occupied = ~np.isin(layer, list(AIR_BLOCKS))
        print(f'== y={y}  occupied={int(occupied.sum())} ==  (x→ right, z↓ down)')
        for z in range(data.length):
            row = []
            for x in range(data.width):
                if not occupied[z, x]:
                    row.append('.')
                else:
                    row.append(classify(base_block(str(layer[z, x]))))
            print(f'{z:3d} ' + ''.join(row))
        print()


def do_crop(data, args):
    raw, _clean, _offset, _cleaning = crop_grid(data, args.bbox)
    volume, palette = encode(raw)
    folder = OUT / args.name
    folder.mkdir(parents=True, exist_ok=True)
    schem = folder / 'probe.schem'
    write_schematic(schem, volume, palette, name=args.name, data_version=data.data_version)
    render_previews(schem, folder, max_size=args.max_size)
    print('probe', args.name, 'bbox', args.bbox, '->', folder)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    p_plan = sub.add_parser('plan')
    p_plan.add_argument('heights', type=int, nargs='+')
    p_crop = sub.add_parser('crop')
    p_crop.add_argument('name')
    p_crop.add_argument('bbox', type=int, nargs=6, metavar=('x0', 'y0', 'z0', 'x1', 'y1', 'z1'))
    p_crop.add_argument('--max-size', type=int, default=900)
    args = parser.parse_args()
    data = load_schematic(SOURCE)
    if args.mode == 'plan':
        plan(data, args.heights)
    else:
        do_crop(data, args)


if __name__ == '__main__':
    main()
