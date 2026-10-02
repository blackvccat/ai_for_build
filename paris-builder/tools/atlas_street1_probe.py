"""Exploration probe for street1 element decomposition: crop a bbox and render it.

Usage (from paris-builder/, PYTHONPATH=src):
    python -X utf8 tools/atlas_street1_probe.py <name> x0 y0 z0 x1 y1 z1 [--max-size 900]

Writes runs/TECHNIQUE-ATLAS-v0.1/probe/<name>/probe.schem + 7 preview PNGs.
Idempotent: re-running overwrites the same probe directory. Read-only on the source.
"""
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from paris_builder.schematic import load_schematic
from paris_builder.source_decomposition import crop, encode
from paris_builder.exporter import write_schematic
from paris_builder.preview3d import render_previews

SOURCE = ROOT.parent / '巴黎建筑素材' / '巴黎民居街区1.schem'
OUT = ROOT / 'runs' / 'TECHNIQUE-ATLAS-v0.1' / 'probe'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name')
    parser.add_argument('bbox', type=int, nargs=6, metavar=('x0', 'y0', 'z0', 'x1', 'y1', 'z1'))
    parser.add_argument('--max-size', type=int, default=900)
    args = parser.parse_args()
    data = load_schematic(SOURCE)
    raw, _clean, _offset, _cleaning = crop(data, args.bbox)
    volume, palette = encode(raw)
    folder = OUT / args.name
    folder.mkdir(parents=True, exist_ok=True)
    schem = folder / 'probe.schem'
    write_schematic(schem, volume, palette, name=args.name, data_version=data.data_version)
    render_previews(schem, folder, max_size=args.max_size)
    print('probe', args.name, 'bbox', args.bbox, '->', folder)


if __name__ == '__main__':
    main()
