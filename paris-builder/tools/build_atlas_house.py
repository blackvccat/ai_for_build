"""ATLAS-HOUSE：用库件组装引擎建造第一栋楼（手法图谱第④步的落地）。

街区1 语汇的 C 类转角公寓：转角在西北角（街面=北 -z 与 西 -x），两翼沿街，
东南两面为共墙素面。除填充/共墙外全部由 knowledge/library-v4/atlas-techniques
的街区1 人工件组装（含 create 壁柱的 7 件不入装，用 vanilla 派生件替代，见报告）。

构建逻辑自 P1 起驻在 src/paris_builder/atlas_street1.py（纯代码平移，
v0.2 哈希字节复现）；本脚本只是 CLI 薄壳，参数与默认值不变。
幂等：每次从零件重搭并覆盖全部产物。

    PYTHONPATH=src python -X utf8 tools/build_atlas_house.py [--seed 6521]
        [--bays-north 5] [--bays-west 4] [--run-dir runs/ATLAS-HOUSE-v0.2]
        [--skip-render] [--probe-rotation]
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from paris_builder import atlas_street1  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=6521)
    parser.add_argument('--bays-north', type=int, default=5)
    parser.add_argument('--bays-west', type=int, default=4)
    parser.add_argument('--run-dir', type=Path, default=PROJECT_ROOT / 'runs' / 'ATLAS-HOUSE-v0.2')
    parser.add_argument('--skip-render', action='store_true')
    parser.add_argument('--probe-rotation', action='store_true',
                        help='只跑旋转约定验证小场景')
    args = parser.parse_args()
    if args.probe_rotation:
        atlas_street1.probe_rotation(args.run_dir)
        return
    _scene, result = atlas_street1.build(args.run_dir, args.seed, args.bays_north,
                                         args.bays_west, args.skip_render)
    if any(result[key]['status'] != 'PASS' for key in
           ('validation', 'independent_registry', 'source_trace', 'stamp_audit')):
        raise SystemExit('ATLAS assembly verification failed; inspect assembly.json before rendering or delivery')


if __name__ == '__main__':
    main()
