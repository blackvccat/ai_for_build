"""用 design.build 主链跑一栋 atlas_street1 转角公寓（plan 驱动，非显式开间数）。

plan_for 校验体量与参数冲突，design.build(work_dir=...) 调 atlas 库件组装引擎，
开间数由 plan.width/depth 按节距序列推导；全部产物（派生件、assembly.json、
ASSEMBLY.md、plan_manifest.json、previews/）落在 --run 目录。

    PYTHONPATH=src python -X utf8 tools/build_atlas_plan.py [--seed 1901]
        [--width 40] [--depth 36] [--tier 3] [--run runs/ATLAS-PLAN-v0.1] [--skip-render]
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from paris_builder import atlas_street1, design  # noqa: E402
from paris_builder.exporter import dump_json  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=1901)
    parser.add_argument('--width', type=int, default=46)
    parser.add_argument('--depth', type=int, default=42)
    parser.add_argument('--composition', choices=('grouped_pavilions', 'flat_baseline'),
                        default='grouped_pavilions')
    parser.add_argument('--tier', type=int, choices=(0, 1, 2, 3), default=0,
                        help='0/1: bare form and layout; 2/3: learned detail kit')
    parser.add_argument('--run', type=Path, default=PROJECT_ROOT / 'runs' / 'ATLAS-PLAN-P2-v0.1')
    parser.add_argument('--skip-render', action='store_true')
    args = parser.parse_args()
    run_dir = args.run.resolve()

    plan = design.plan_for('corner_house', seed=args.seed, width=args.width,
                           depth=args.depth, detail_profile='atlas_street1',
                           composition_profile=args.composition)
    scene, manifest = design.build(plan, work_dir=run_dir, tier=args.tier)
    gates = {key: manifest[key]['status'] for key in
             ('validation', 'independent_registry', 'source_trace', 'atlas_audit')}
    allowed = ('PASS', 'NOT_APPLICABLE') if args.tier < 2 else ('PASS',)
    renders = None
    if not args.skip_render and all(status in allowed for status in gates.values()):
        renders = atlas_street1.render(PROJECT_ROOT / manifest['schematic']['path'], run_dir / 'previews')
        manifest['renders'] = renders
    dump_json(run_dir / 'plan_manifest.json', manifest)
    print('plan:', manifest['plan'])
    print('bays: north=%s west=%s' % (manifest['scene']['bays_north'],
                                      manifest['scene']['bays_west']))
    print('cells: %d | gates: %s | renders: %s' % (
        int((scene.volume != 0).sum()), gates,
        renders['out_dir'] if renders else 'SKIPPED'))
    if any(status not in allowed for status in gates.values()):
        raise SystemExit('ATLAS plan build verification failed; inspect assembly.json')


if __name__ == '__main__':
    main()
