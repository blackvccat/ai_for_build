"""Render probe crops from 巴黎建筑素材6 into runs/TECHNIQUE-ATLAS-v0.1/probe_crops/.

Read-only on the source: crop -> write temp schem -> 7-view previews, so candidate
b6-* bounding boxes can be checked visually before the real decomposition runs.
Usage: python -X utf8 tools/atlas_b6_crop_probe.py x0 y0 z0 x1 y1 z1 name
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from paris_builder.source_decomposition import crop, encode
from paris_builder.schematic import load_schematic
from paris_builder.exporter import write_schematic
from paris_builder.preview3d import render_previews

SOURCE = ROOT.parent / '巴黎建筑素材' / '巴黎建筑素材6.schem'
OUT = ROOT / 'runs/TECHNIQUE-ATLAS-v0.1/probe_crops'


def main():
    bounds, name = [int(v) for v in sys.argv[1:7]], sys.argv[7]
    data = load_schematic(SOURCE)
    raw, cleaned, offset, cleaning = crop(data, bounds)
    folder = OUT / name
    folder.mkdir(parents=True, exist_ok=True)
    volume, palette = encode(cleaned)
    write_schematic(folder / 'crop.schem', volume, palette, name=name, data_version=4671)
    print('offset', offset, 'shape(y,z,x)', cleaned.shape, flush=True)
    render_previews(folder / 'crop.schem', folder / 'previews', max_size=700)


if __name__ == '__main__':
    main()
