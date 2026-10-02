# -*- coding: utf-8 -*-
"""Validate the roof measurement on a real export before trusting any predicate."""
import json
import sys

sys.path.insert(0, 'src')

from paris_builder import atlas_geometry as G  # noqa: E402
from paris_builder.schematic import load_schematic  # noqa: E402

PATH = sys.argv[1] if len(sys.argv) > 1 else 'runs/ATLAS-FRAME-PROBE-v5/ATLAS-FRAME.schem'
read = load_schematic(PATH)
report = G.roof_plane(read)
print('file  :', PATH)
print('status:', report['status'])
if report['status'] != 'MEASURED':
    print(json.dumps(report, ensure_ascii=False)[:400])
    raise SystemExit(1)

print('method:', report['method'])
print('footprint:', report['bounds_xz'], 'wd=', report['footprint_wd'])
print('roof cells=%d  attached cells=%d' % (report['roof_cells'], report['attached_cells']))
print('max raw top y = %d   max plane top y = %d' % (report['max_raw_top_y'], report['max_plane_top_y']))
print()
print('distance bands (low = plane, high = anything standing on it):')
for row in report['bands'][:16]:
    print('  d=%-3d n=%-5d low=%-4s median=%-4s high=%-4s'
          % (row['distance'], row['samples'], row['low'], row['median'], row['high']))
print()
print('attached volume clusters (top 6):')
for row in report['attached_clusters'][:6]:
    print('  cells=%-4d z=%-9s x=%-9s max_rise=%-3d top_y=%d'
          % (row['cells'], row['z_range'], row['x_range'], row['max_rise'], row['top_y']))

print()
print('=== wing-restricted eave profiles (the only kind that means anything) ===')
# Wing geometry from the assembly constants: north wing starts at x=10 and runs 23 deep
# (z 0..22); west wing starts at z=11 and runs 23 deep (x 0..22).
WING = 23
for face, span in (('north', (10, 44)), ('west', (11, 41))):
    prof = G.eave_profile(report, face, span=span, limit=WING)
    rows = [r for r in prof['profile'] if r['plane_y'] is not None]
    print('=== %s wing  span=%s limit=%d ===' % (face, span, WING))
    print('  distance:', [r['distance'] for r in rows])
    print('  plane_y :', [r['plane_y'] for r in rows])
    print('  high_y  :', [r['high_y'] for r in rows])
    print('  slope segments:')
    for seg in G.slope_segments(prof):
        print('     d %-9s y %-9s rise/run=%s' % (seg['distance'], seg['y'], seg['rise_per_run']))
    rule = G.forty_five_degree(prof)
    print('  45-degree rule: %s  eave_y=%s ridge_y=%s roof_height=%s'
          % (rule['status'], rule.get('eave_y'), rule.get('ridge_y'), rule.get('roof_height')))
    print('     tightest: %s' % rule.get('tightest'))
    if rule.get('violations'):
        print('     violations:', rule['violations'][:5])
    print()
