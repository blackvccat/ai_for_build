# -*- coding: utf-8 -*-
"""One-shot validation: resolve the spec, check it, and see what it catches.

Compares the dry run against the real build's wall-clock cost, and reports whether the
slot predicates and the declared style rules agree with what the built frame actually is.
"""
import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, 'src')

from paris_builder import atlas_rules as R  # noqa: E402
from paris_builder import atlas_slots as S  # noqa: E402

SRC = Path('runs/ATLAS-FRAME-PROBE-v5/composition.json')
SCRATCH = Path('runs/ATLAS-SLOTS-PROBE')

composition = json.load(io.open(SRC, encoding='utf-8'))
print('composition :', SRC)
print('  mode      :', composition['mode'])
print('  plan      :', composition['plan'])
print('  rhythm    :', composition['rhythm'])
print('  north bays:', composition['wings']['north']['bay_count'],
      ' west bays:', composition['wings']['west']['bay_count'])
print()

SCRATCH.mkdir(parents=True, exist_ok=True)
started = time.time()
plan = S.resolve(composition, SCRATCH)
elapsed = time.time() - started
print('=== DRY RUN (no voxel written) ===')
print('  wall clock : %.2f s' % elapsed)
print('  scene      :', plan['scene'])
print('  stamps     : %d' % len(plan['stamps']))
print('  derived    : %d pieces' % len(plan['derived_pieces']))
print('  fill       :', json.dumps(plan['fill'], ensure_ascii=False)[:160])
print('  nonair     :', plan['scene_nonair_cells'], '(must be 0 - nothing was written)')
print()
roles = {}
for row in plan['stamps']:
    roles[row['role']] = roles.get(row['role'], 0) + 1
print('  roles placed (%d distinct):' % len(roles))
for name in sorted(roles):
    print('     %-26s x%d' % (name, roles[name]))
print()

style = R.load_style()
results = S.validate_slots(plan, style)
print('=== SLOT PLAN VALIDATION ===')
for row in results:
    mark = {'PASS': 'OK  ', 'FAIL': 'FAIL', 'UNMEASURED': '  ? '}[row['status']]
    print('  [%s] %-24s %s' % (mark, row['rule'], str(row.get('detail'))[:110]))
payload = S.write_report(SCRATCH / 'slot-validation.json', plan, results)
print()
print('  ->', json.dumps({'status': payload['status'], 'counts': payload['counts'],
                          'failed': payload['failed_rules'],
                          'unmeasured': payload['unmeasured_rules']}, ensure_ascii=False))
print('  report:', SCRATCH / 'slot-validation.json')
