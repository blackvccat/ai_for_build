"""Measure per-face-role differentiation of the built stage-1 framework.

Reads a recorded assembly_plan.json so the conclusion comes from real generator
output rather than from reading the generator source and guessing.
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

plan = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
faces = plan['face_graph']['faces']
print('face count:', len(faces))
print('sample face keys:', sorted(faces[0]))
by_id = {f.get('face_id') or f.get('id'): f for f in faces}
for f in faces:
    fid = f.get('face_id') or f.get('id')
    print('  %-4s role=%-16s diagonal=%s u_count=%s' % (fid, f.get('role'), f.get('diagonal'),
                                                        f.get('length') or f.get('u_length') or '?'))

placements = plan['placements']
per_face_components = defaultdict(Counter)
for p in placements:
    fid = p.get('face') or p.get('face_id')
    role = (by_id.get(fid) or {}).get('role', '?')
    per_face_components[role][p.get('component_id') or p.get('family', '?')] += 1
print('\ncomponents placed per face role:')
for role, counter in sorted(per_face_components.items()):
    print('  %-16s %s' % (role, dict(counter)))

openings = plan.get('openings', [])
widths = defaultdict(Counter)
for o in openings:
    widths[o.get('role')][o.get('width')] += 1
print('\nopening widths per role (width -> count):')
for role, counter in sorted(widths.items()):
    print('  %-16s %s' % (role, dict(sorted(counter.items()))))
