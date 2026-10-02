# -*- coding: utf-8 -*-
"""Run the nine declared Haussmann rules against the real v5 frame."""
import io
import json
import sys

sys.path.insert(0, 'src')

from paris_builder import atlas_rules as R  # noqa: E402
from paris_builder.schematic import load_schematic, base_block, AIR_BLOCKS  # noqa: E402

FRAME = 'runs/ATLAS-FRAME-PROBE-v5/frame.json'
SCHEM = 'runs/ATLAS-FRAME-PROBE-v5/ATLAS-FRAME.schem'

frame = json.load(io.open(FRAME, encoding='utf-8'))
spec = frame['atlas_frame_spec']
composition = frame['composition']

# Wing geometry comes from the assembly driver constants, not from the spec (yet).
import paris_builder.atlas_street1 as kit  # noqa: E402
xs_north = [row for row in composition['wings']['north']['bays']]
span = (kit.BAY_START_NORTH, kit.BAY_START_NORTH + 34)
spec['north_wing_span'] = list(span)
spec['wing_depth'] = kit.WING_DEPTH

style = R.load_style()
print('style:', style['_source'], '| status:', style.get('status'))
print()

print('=== SPEC rules (decidable before a single block is written) ===')
spec_results = R.spec_checks(style, composition, spec)
for row in spec_results:
    print('  %-24s %-12s %s' % (row['rule'], row['status'], str(row['detail'])[:110]))
print('  ->', json.dumps(R.summarize(spec_results), ensure_ascii=False))

print()
print('=== EXPORT rules (need the built schematic) ===')
read = load_schematic(SCHEM)
names = {int(i): base_block(v) for i, v in
         (read.id_to_state.items() if isinstance(read.id_to_state, dict)
          else enumerate(read.palette))}
base_y = spec['fixed_levels'].get('standard_base') or 0
base_mats, body_mats = set(), set()
for index, state in (read.id_to_state.items() if isinstance(read.id_to_state, dict)
                     else enumerate(read.palette)):
    name = base_block(state)
    if name in AIR_BLOCKS:
        continue
    # coarse: split by whether the material appears mostly below or above the base line
    top = max((y for y in range(read.volume.shape[0])
               if (read.volume[y] == int(index)).any()), default=-1)
    (base_mats if top <= base_y + 2 else body_mats).add(name)
export_results = R.export_checks(style, read, spec,
                                 material_split={'base': base_mats, 'body': body_mats})
for row in export_results:
    print('  %-24s %-12s measured=%-28s expected=%s'
          % (row['rule'], row['status'], str(row.get('measured'))[:28], str(row.get('expected'))[:24]))
    print('      %s' % str(row['detail'])[:150])
print('  ->', json.dumps(R.summarize(export_results), ensure_ascii=False))

print()
print('=== ALL NINE ===')
allr = spec_results + export_results
for row in allr:
    mark = {'PASS': 'OK  ', 'FAIL': 'FAIL', 'UNMEASURED': '  ? '}[row['status']]
    print('  [%s] %-24s (%s) %s' % (mark, row['rule'], row['kind'],
                                    str(row.get('declared_rule') or '')[:70]))
print('  ->', json.dumps(R.summarize(allr), ensure_ascii=False))
