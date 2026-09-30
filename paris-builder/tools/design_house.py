"""Print the design matrix and the per-wall openings of one house.

Used while developing the three layers: a form whose street face reports almost no
openings is a bug in the composition, and reading the numbers is faster than reading a
render.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from paris_builder import design  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--form', default=None)
    parser.add_argument('--scheme', default=None)
    parser.add_argument('--seed', type=int, default=1900)
    parser.add_argument('--matrix', action='store_true')
    parser.add_argument('--json', type=Path, default=None)
    args = parser.parse_args()

    if args.matrix or not args.form:
        rows = design.matrix(seed=args.seed)
        print('%-18s %-20s %6s %7s %6s %6s' % ('form', 'scheme', 'open', 'street', 'tech', 'cells'))
        for row in rows:
            print('%-18s %-20s %6d %7d %6d %6d' % (row['form'], row['scheme'], row['openings'],
                                                   row['street_openings'], row['technique_count'],
                                                   row['cells']))
        if args.json:
            args.json.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding='utf-8')
        return

    plan = design.plan_for(args.form, seed=args.seed, scheme=args.scheme)
    scene, manifest = design.build(plan)
    print(json.dumps(manifest['plan'], ensure_ascii=False, indent=2))
    print('\nlevels: %s' % [(l['name'], l['y'], l['height']) for l in manifest['structure']['levels']])
    for wall in manifest['walls']:
        print('  %-14s %-9s len=%2d openings=%2d bays=%d widths=%s piers=%s' % (
            wall['name'], wall['role'], wall['length'], wall['openings'], wall['bay_groups'],
            wall['group_widths'], wall['pier_widths']))
    print('\ntechniques: %s' % manifest['techniques'])
    print('scheme expects: %s' % manifest['scheme_expects'])
    missing = [t for t in manifest['scheme_expects'] if t not in manifest['techniques']]
    print('missing from the scheme: %s' % (missing or 'none'))
    print('cells: %d' % int((scene.volume != 0).sum()))
    return


if __name__ == '__main__':
    raise SystemExit(main())
