"""Render the two street fronts of a north-west corner from its real schematic."""
import argparse
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from paris_builder.exporter import dump_json
from paris_builder.preview3d import Assets, DEFAULT_CACHE, _mesh, _render, ensure_assets
from paris_builder.schematic import load_schematic


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    schematic = args.run / 'ATLAS-HOUSE.schem'
    out = args.run / 'previews'
    out.mkdir(parents=True, exist_ok=True)
    read = load_schematic(schematic)
    assets = Assets(ensure_assets(DEFAULT_CACHE))
    mesh = _mesh(read, assets)
    direction = (-1.6, 0.8, -2.2)
    result = _render(mesh, assets, direction,
                     'North-west street corner / true block models',
                     out / 'street_corner.png', 1700)
    dump_json(out / 'street_corner_metadata.json', {
        'source_schematic': str(schematic.resolve()),
        'source_sha256': hashlib.sha256(schematic.read_bytes()).hexdigest(),
        'camera_direction': list(direction), 'render': result,
        'purpose': 'Observe the north and west street fronts together; not game acceptance',
    })
    print(out / 'street_corner.png')


if __name__ == '__main__':
    main()
