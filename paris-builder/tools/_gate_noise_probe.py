# -*- coding: utf-8 -*-
"""Is the visual gate a measuring instrument, or a noise source?

The facade stage has rejected 22 consecutive candidates whose scores straddle the
gate (72..86, gate 80). Before blaming the generator, test the instrument: if the
SAME artifact (identical artifact_hashes) is reviewed twice and scores differently,
then no amount of generator repair can converge — the loop is waiting for a noisy
judge to agree with itself.
"""
import io
import json
from collections import defaultdict

RUN = 'runs/ATELIER-A9B3C7EE/workflow.json'
w = json.load(io.open(RUN, encoding='utf-8'))

print('=== every review, keyed by (stage, revision, artifact_hashes) ===')
by_artifact = defaultdict(list)
for r in w['reviews']:
    if r['stage'] not in ('frameworks', 'facades'):
        continue
    scores = [c.get('scores') for c in r.get('candidates', [])]
    totals = [sum(s) for s in scores if isinstance(s, list) and len(s) == 5]
    fails = 0
    for c in r.get('candidates', []):
        for group in [c.get('geometry_checks') or {}] + list((c.get('detail_checks') or {}).values()) \
                     + list((c.get('storey_checks') or {}).values()):
            fails += sum(1 for v in group.values() if isinstance(v, dict) and v.get('status') == 'fail')
        fails += sum(1 for v in (c.get('layer_checks') or {}).values()
                     if isinstance(v, dict) and v.get('status') == 'fail')
    key = (r['stage'], tuple(sorted((r.get('artifact_hashes') or {}).items())))
    by_artifact[key].append({'rev': r.get('revision'), 'decision': r['decision'],
                             'totals': totals, 'fails': fails,
                             'modes': [str(x)[:110] for x in (r.get('candidates') or [{}])[0].get('failure_modes', [])][:3]})

repeat = {k: v for k, v in by_artifact.items() if len(v) > 1}
print('distinct artifacts reviewed : %d' % len(by_artifact))
print('artifacts reviewed 2+ times : %d' % len(repeat))
print()

if repeat:
    print('=== SAME artifact, repeated reviews ===')
    for (stage, _), rows in sorted(repeat.items(), key=lambda kv: -len(kv[1])):
        totals = [t for row in rows for t in row['totals']]
        fails = [row['fails'] for row in rows]
        print('  %-11s x%d  revs=%s' % (stage, len(rows), sorted({r['rev'] for r in rows})))
        print('     scores : %s   spread=%d' % (totals, (max(totals) - min(totals)) if totals else 0))
        print('     fails  : %s   spread=%d' % (fails, max(fails) - min(fails)))
        for row in rows:
            print('       rev %-4s %-6s total=%s fails=%d' % (row['rev'], row['decision'], row['totals'], row['fails']))
        print('     first failure modes of one review:')
        for m in rows[0]['modes']:
            print('       - %s' % m)
        print()

print('=== score distribution across ALL facade reviews ===')
totals = [t for r in w['reviews'] if r['stage'] == 'facades'
          for c in r.get('candidates', [])
          for s in [c.get('scores')] if isinstance(s, list) and len(s) == 5
          for t in [sum(s)]]
totals.sort()
print('  n=%d  min=%d  max=%d  mean=%.1f' % (len(totals), min(totals), max(totals), sum(totals) / len(totals)))
print('  sorted: %s' % totals)
at_or_above = sum(1 for t in totals if t >= 80)
print('  >= 80 (gate satisfied on score): %d / %d = %.0f%%' % (at_or_above, len(totals), 100 * at_or_above / len(totals)))
print('  passes: %d' % sum(1 for r in w['reviews'] if r['stage'] == 'facades' and r['decision'] == 'pass'))
