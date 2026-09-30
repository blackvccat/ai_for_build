"""Print the voxel stack through one facade column, so facade bugs are visible.

A render shows the *result* of a wrong write order; this shows the write order's
output cell by cell. Used because the earlier city renders were misdiagnosed twice.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from paris_builder.schematic import load_schematic


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('schematic', type=Path)
    parser.add_argument('--x', type=int, required=True)
    parser.add_argument('--z0', type=int, required=True)
    parser.add_argument('--z1', type=int, required=True)
    parser.add_argument('--y0', type=int, default=0)
    parser.add_argument('--y1', type=int, default=48)
    args = parser.parse_args()

    data = load_schematic(args.schematic)
    volume, states = data.volume, data.id_to_state
    for y in range(args.y0, args.y1):
        cells = []
        for z in range(args.z0, args.z1 + 1):
            value = states[int(volume[y, z, args.x])]
            cells.append('%3d:%-28s' % (z, value.replace('minecraft:', '')))
        print('y=%2d | %s' % (y, ' '.join(cells)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
