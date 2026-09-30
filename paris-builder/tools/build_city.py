#!/usr/bin/env python3
"""Build one Paris street (two parcel rows sharing party walls) and render it.

This is the city layer's entry point: it lays out the street and parcels from the
city spec, assembles the street wall, writes the .schem plus a per-block manifest,
and renders the views the way the rest of the project does.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from paris_builder.city import StreetCity, facade_report  # noqa: E402
from paris_builder.exporter import dump_json, write_schematic  # noqa: E402
from paris_builder.geometry import inspect_geometry  # noqa: E402
from paris_builder.preview3d import render_previews  # noqa: E402
from paris_builder.schematic import load_schematic  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', default='CITY-v0.1')
    parser.add_argument('--seed', type=int, default=1900)
    parser.add_argument('--length', type=int, default=210)
    parser.add_argument('--size', type=int, default=1000)
    parser.add_argument('--no-render', action='store_true')
    args = parser.parse_args()

    out = ROOT / 'runs' / args.run
    out.mkdir(parents=True, exist_ok=True)

    city = StreetCity(args.seed, street_length=args.length)
    scene = city.assemble()
    schematic = out / 'CITY.schem'
    write_schematic(schematic, scene.volume, scene.palette, name='PARIS-CITY %d' % args.seed)
    read = load_schematic(schematic)
    validation = read.validation()
    geometry = inspect_geometry(read)
    # The street face is scored as a gate, not as a side tool: a wall whose windows are
    # not on the plane the street sees still passes file and geometry validation, which
    # is how four city renders were signed off with an invisible facade.
    faces = {side: facade_report(city, side) for side in ('north', 'south')}
    dump_json(out / 'validation.json', validation)
    dump_json(out / 'geometry_validation.json', geometry)
    dump_json(out / 'facade_score.json', faces)
    dump_json(out / 'city_manifest.json', city.manifest())
    gates = {'file_validation': validation['status'], 'geometry': geometry['status'],
             'street_face': 'PASS' if all(f['verdict'] == 'PASS' for f in faces.values()) else 'FAIL'}
    report = {
        'status': 'PASS' if all(value == 'PASS' for value in gates.values()) else 'FAIL',
        **gates,
        'dimensions_whl': [read.width, read.height, read.length],
        'parcels': len(city.parcels),
        'storey_heights': sorted({b['storeys'] for b in city.street_blocks}),
        'frontage_range': [min(b['frontage'] for b in city.street_blocks),
                           max(b['frontage'] for b in city.street_blocks)],
        'facade': {side: {'glazing_share': round(f['glazing_share'], 4),
                          'window_cells': f.get('window_cells'),
                          'window_groups': f['window_groups'],
                          'glazed_columns': f['glazed_columns'],
                          'door_cells': f['door_cells'],
                          'open_cells': f['open_cells']} for side, f in faces.items()},
        'game_acceptance': 'PENDING',
        'note': 'City layer only. Structure/facade/technique layers are selected from these parcels; '
                'this is not a game paste test and not user acceptance.',
    }
    dump_json(out / 'city_report.json', report)
    if not args.no_render:
        render_previews(schematic, out / 'previews', max_size=args.size, orbit=False)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
