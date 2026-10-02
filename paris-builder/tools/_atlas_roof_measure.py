# -*- coding: utf-8 -*-
"""Measure the atlas frame's roof from the export, before writing any predicate.

I claimed the v5 roof was "too tall". Check the Paris 45-degree rule properly: the
roof must fit under a 45-degree line from the eave, so at horizontal distance d from
the eave the roof may rise at most d. Whether that is violated is arithmetic on the
measured profile, not an impression from a render.
"""
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, 'src')

from paris_builder.schematic import load_schematic, base_block, AIR_BLOCKS  # noqa: E402

PATH = 'runs/ATLAS-FRAME-PROBE-v5/ATLAS-FRAME.schem'
s = load_schematic(PATH)
volume = s.volume
states = s.id_to_state if isinstance(s.id_to_state, dict) else {i: v for i, v in enumerate(s.palette)}
height, depth, width = volume.shape
print('%s  shape=(h=%d, d=%d, w=%d)' % (PATH, height, depth, width))

names = {}
for index, state in states.items():
    names[int(index)] = base_block(state)
air = {i for i, n in names.items() if n in AIR_BLOCKS}
roof_family = {i for i, n in names.items()
               if 'deepslate' in n or 'blackstone' in n or 'basalt' in n}
glass = {i for i, n in names.items() if 'glass' in n}

counts = Counter(names[int(i)] for i in np.unique(volume) if int(i) not in air)
print('materials:', dict(counts.most_common(8)))

# Occupancy per column and roof-family top per column.
solid = ~np.isin(volume, list(air))
roofmask = np.isin(volume, list(roof_family))
nonair_top = np.full((depth, width), -1, dtype=int)
for y in range(height):
    rows = np.where(solid[y].any(axis=1))[0]
    if len(rows) == 0:
        continue
    cols = np.where(solid[y])[1]
    for z, x in zip(*np.where(solid[y])):
        nonair_top[z, x] = y
roof_top = np.full((depth, width), -1, dtype=int)
for y in range(height):
    for z, x in zip(*np.where(roofmask[y])):
        roof_top[z, x] = y

occupied = nonair_top >= 0
zs, xs = np.where(occupied)
z0, z1, x0, x1 = zs.min(), zs.max(), xs.min(), xs.max()
print('footprint x=[%d..%d] z=[%d..%d]  cells=%d' % (x0, x1, z0, z1, occupied.sum()))

# The eave = the height where the footprint is widest (facade top). Find the roof datum.
row_width = [(y, int(solid[y].sum())) for y in range(height)]
widest_y, widest_n = max(row_width, key=lambda row: row[1])
tops = [v for v in nonair_top[occupied]]
print('eave candidate y=%d (widest row, %d cells)' % (widest_y, widest_n))
print('highest solid y=%d' % max(tops))

ridge_y = int(np.percentile(tops, 98))
print('ridge (98th pct of column tops) y=%d' % ridge_y)

print()
print('=== 45-degree rule, per wing face ===')
# North face is z_min; the roof runs from that eave inward along +z.
for label, axis, fixed_range, eave_coord, direction in (
        ('north eave (z min) -> inward +z', 'z', (x0, x1), z0, +1),
        ('west eave (x min) -> inward +x', 'x', (z0, z1), x0, +1)):
    profile = []
    for u in fixed_range:
        if axis == 'z':
            column = [nonair_top[z, u] for z in range(z0, z1 + 1)]
        else:
            column = [nonair_top[u, x] for x in range(x0, x1 + 1)]
        profile.append(column)
    if not profile:
        continue
    length = len(profile[0])
    # median top height at each distance from the eave
    heights = []
    for d in range(length):
        values = [col[d] for col in profile if col[d] >= 0]
        heights.append(int(np.median(values)) if values else None)
    base = next((h for h in heights if h is not None), None)
    print('  %s   eave_y=%s' % (label, base))
    print('    distance->top:', heights[:24])
    if base is not None:
        violations = [(d, h) for d, h in enumerate(heights[:24])
                      if h is not None and d > 0 and (h - base) > d]
        print('    45deg violations (rise > distance):', violations if violations else 'none')
        rises = [h - base for h in heights[:24] if h is not None]
        print('    rise from eave   :', rises)

print()
print('=== slope legibility: per-column rise between consecutive cells ===')
step_counts = Counter()
for z in range(z0, z1 + 1):
    row = [nonair_top[z, x] for x in range(x0, x1 + 1)]
    for a, b in zip(row, row[1:]):
        if a >= 0 and b >= 0:
            step_counts[b - a] += 1
print('  delta distribution:', dict(sorted(step_counts.items())))
print('  (a mansard should show two regimes: a large positive delta band then a small one)')

print()
print('=== roof-family share of the facade height ===')
body_top = widest_y
print('  body/eave y=%d   ridge y=%d   roof height=%d cells   facade height=%d cells'
      % (body_top, ridge_y, ridge_y - body_top, body_top - 0 + 1))
print('  roof / facade = %.0f%%' % (100.0 * (ridge_y - body_top) / max(1, body_top + 1)))

print()
print('=== eave width available for the 45-degree rule ===')
print('  footprint width (x) = %d  depth (z) = %d' % (x1 - x0 + 1, z1 - z0 + 1))
print('  half-depth = %d  -> a mansard may rise at most %d cells above the eave'
      % ((z1 - z0 + 1) // 2, (z1 - z0 + 1) // 2))
