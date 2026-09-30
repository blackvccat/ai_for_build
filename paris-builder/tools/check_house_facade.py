"""Check that a rendered house facade has glazing on the plane the street sees.

Same lesson as the city layer: a render cannot distinguish "the windows are too dark"
from "the windows were never written", so this reads the voxels. It walks the street
wall's own surface plane (`d = 0`) and reports what is on it.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from paris_builder import design  # noqa: E402
from paris_builder.architecture import split_state  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--form', default='street_house')
    parser.add_argument('--scheme', default=None)
    parser.add_argument('--seed', type=int, default=1900)
    parser.add_argument('--width', type=int, default=None)
    parser.add_argument('--depth', type=int, default=None)
    args = parser.parse_args()

    plan = design.plan_for(args.form, seed=args.seed, scheme=args.scheme,
                           width=args.width, depth=args.depth)
    scene, manifest = design.build(plan)
    palette, volume = scene.palette, scene.volume
    print('%s + %s  %dx%d storeys=%d' % (plan.form, plan.scheme, plan.width, plan.depth,
                                         plan.storeys))
    for wall_report in manifest['walls']:
        if wall_report['role'] != 'primary':
            continue
        # Rebuild the wall object to get its geometry back.
        structure, _ctx = design.structure_layer.build(plan.form, plan.width, plan.depth,
                                                       plan.storeys, plan.seed)
        wall = next(w for w in structure.walls if w.name == wall_report['name'])
        counts = Counter()
        columns = []
        for u in range(wall.length):
            seen = False
            for y in range(1, wall.height + 1):
                x, _yy, z = wall.point(u, y, 0)
                name, _ = split_state(palette[int(volume[y, z, x])])
                counts[name] += 1
                seen = seen or name.startswith('minecraft:white_stained_glass')
            columns.append(seen)
        total = sum(counts.values())
        glazing = sum(v for k, v in counts.items() if k.startswith('minecraft:white_stained_glass'))
        print('\nwall %s: %d surface cells' % (wall.name, total))
        for name, count in counts.most_common(7):
            print('   %-44s %5d  %5.1f%%' % (name, count, 100.0 * count / total))
        runs, start = [], None
        for index, value in enumerate(columns):
            if value and start is None:
                start = index
            elif not value and start is not None:
                runs.append((start, index - 1))
                start = None
        if start is not None:
            runs.append((start, len(columns) - 1))
        print('\nglazing cells on the street plane: %d (%.1f%%)' % (glazing, 100.0 * glazing / total))
        print('glazed column groups: %d  %s' % (len(runs), runs))
        # Which storeys actually carry glazing: a facade whose windows are all on one
        # band is a different defect from one with no windows at all.
        print('\nglazing per y (u range 0..%d):' % (wall.length - 1))
        for y in range(1, wall.height + 1):
            cells = []
            for u in range(wall.length):
                x, _yy, z = wall.point(u, y, 0)
                name, _ = split_state(palette[int(volume[y, z, x])])
                cells.append('G' if name.startswith('minecraft:white_stained_glass')
                             else ('.' if name == 'minecraft:air' else '-'))
            row = ''.join(cells)
            if 'G' in row or row.strip('-') == '':
                print('   y=%2d  %s' % (y, row))
        print('\nverdict: %s' % ('PASS' if glazing and len(runs) >= 2 else 'FAIL'))
    return


if __name__ == '__main__':
    raise SystemExit(main())
