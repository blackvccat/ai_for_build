"""Render the *street* face of a city schematic.

The fixed preview cameras are defined for one detached building: `front` is
north/z_min. A street, though, has to be looked at from inside the street —
southwards for the north row — and no built-in view does that. This tool turns
the schematic 180 degrees about the vertical axis, renders it with the normal
renderer, and keeps the resulting `front.png`, which is now the street face.

Turning the model rather than adding a camera keeps `preview3d` byte-identical
for the frozen PAR-002 delivery, whose renders are part of the audit trail.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np

from paris_builder.exporter import write_schematic
from paris_builder.preview3d import render_previews
from paris_builder.schematic import load_schematic


def turned_volume(data, crop=None):
    """Rotate the voxel grid 180 degrees about y, so z_max faces the camera.

    `Scene.volume` and the loaded schematic volume are both shaped (y, z, x), so the
    two axes to turn about are 1 (z) and 2 (x).
    """
    volume = data.volume
    if crop:
        x0, x1, z0, z1 = crop
        volume = volume[:, z0:z1 + 1, x0:x1 + 1]
    return np.rot90(volume, k=2, axes=(1, 2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('schematic', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--max-size', type=int, default=1000)
    parser.add_argument('--crop', type=int, nargs=4, metavar=('X0', 'X1', 'Z0', 'Z1'),
                        help='keep only this box, so one house can be seen at full scale')
    parser.add_argument('--keep', action='store_true', help='keep the turned schematic')
    args = parser.parse_args()

    data = load_schematic(args.schematic)
    volume = turned_volume(data, args.crop)
    args.out.mkdir(parents=True, exist_ok=True)
    turned = args.out / 'turned.schem'
    # Palette order must match the ids inside `volume`, so keep the source array.
    states = [data.id_to_state[i] for i in range(len(data.id_to_state))]
    write_schematic(turned, volume, states, name='City street view (turned)')

    tmp = args.out / '_render'
    paths = render_previews(turned, tmp, max_size=args.max_size)
    # After the turn the face that was at the parcel's z_max (the street face of the
    # north row) is at z_min, which is what the *front* camera shows. The file is also
    # copied under a name that says so, because reading the wrong one of these cost
    # three iterations.
    street = args.out / 'street_face.png'
    shutil.copyfile(paths['front'], street)
    axonometric = args.out / 'street_axonometric.png'
    shutil.copyfile(paths['axonometric_front'], axonometric)
    rear = args.out / 'rear_face.png'
    shutil.copyfile(paths['back'], rear)
    report = {'source': str(args.schematic.resolve()), 'street_face': str(street.resolve()),
              'street_axonometric': str(axonometric.resolve()),
              'dimensions_whl': [data.width, data.height, data.length], 'crop': args.crop,
              'note': 'front.png of the turned model = the face seen from inside the street'}
    (args.out / 'street_view.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    if not args.keep:
        turned.unlink()
    print(json.dumps({'street_face': report['street_face'], 'axonometric': report['street_axonometric']}, indent=2))


if __name__ == '__main__':
    main()
