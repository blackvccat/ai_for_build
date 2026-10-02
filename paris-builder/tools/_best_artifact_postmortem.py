# -*- coding: utf-8 -*-
"""The best artifact the run ever produced was thrown away. What rejected it?

rev 59 scored 86 (gate 80) with only 2 failed checks out of ~95 - the cleanest
candidate in 27 revisions. It was rejected and never revisited. If those 2 fails
are "cannot see it from these renders", the gate is not measuring the building.
"""
import io
import json

w = json.load(io.open('runs/ATELIER-A9B3C7EE/workflow.json', encoding='utf-8'))

target = None
for r in w['reviews']:
    if r['stage'] != 'facades':
        continue
    for c in r.get('candidates', []):
        s = c.get('scores')
        if s and len(s) == 5 and sum(s) == 86:
            target = (r, c)
if not target:
    print('rev 59 / 86 not found')
    raise SystemExit(1)

r, c = target
print('revision %s   decision=%s   scores=%s (total %d)' % (r.get('revision'), c.get('decision'),
                                                            c.get('scores'), sum(c.get('scores'))))
print()
print('=== every failed check and its observation ===')
groups = [('geometry_checks', c.get('geometry_checks') or {})]
groups += [('detail_checks/' + k, v) for k, v in (c.get('detail_checks') or {}).items()]
groups += [('storey_checks/' + k, v) for k, v in (c.get('storey_checks') or {}).items()]
for name, group in groups:
    for key, value in (group or {}).items():
        if isinstance(value, dict) and value.get('status') == 'fail':
            print('  [%s] %s' % (name, key))
            print('      %s' % str(value.get('observation'))[:400])
for key, value in (c.get('layer_checks') or {}).items():
    if isinstance(value, dict) and value.get('status') == 'fail':
        print('  [layer_checks] %s' % key)
        print('      %s' % str(value.get('observation'))[:400])

print()
print('=== failure_modes ===')
for m in (c.get('failure_modes') or []):
    print('  - %s' % str(m)[:300])

print()
print('=== how many checks passed vs failed ===')
passed = na = failed = 0
for name, group in groups:
    for value in (group or {}).values():
        if isinstance(value, dict):
            status = value.get('status')
            passed += status == 'pass'
            na += status == 'not_applicable'
            failed += status == 'fail'
for value in (c.get('layer_checks') or {}).values():
    if isinstance(value, dict):
        status = value.get('status')
        passed += status == 'pass'
        na += status == 'not_applicable'
        failed += status == 'fail'
print('  pass=%d  not_applicable=%d  fail=%d  (total %d)' % (passed, na, failed, passed + na + failed))
