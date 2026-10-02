# -*- coding: utf-8 -*-
"""Is the roof measurement reporting chimneys as slope spikes?

The best artifact the run ever produced (rev 59: score 86, 53 pass / 40 n/a / 2 fail)
was rejected because the measured roof section showed "local spikes (rise 10 vs 8)"
and "a null column", so the mansard slope break "cannot be verified".

The section is sampled as the TOPMOST roof-family voxel per column. A chimney is a
roof-family voxel that stands above the roof, and a dormer interrupts it - so both
legitimate features inject exactly the spikes and nulls the reviewer is failing on.

Test: take a real artifact, extract the roof columns, and separate "attached volume"
(isolated tall column) from "roof surface" (part of a broad monotone run).
"""
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, 'src')

path = sorted(Path('runs/ATELIER-A9B3C7EE').glob('revision-*/facades/facade-1/facade_section*.json'),
              key=lambda p: p.stat().st_mtime)[-1]
print('report:', path)
report = json.load(io.open(path, encoding='utf-8'))
print('status:', report.get('status'))

roof = report.get('roof_section') or {}
print('last_floor_y:', roof.get('last_floor_y'))
print('measured_roof_columns:', roof.get('measured_roof_columns'))
print('policy:', str(roof.get('section_policy'))[:160])
print()

samples = roof.get('samples') or []
print('=== samples: %d lines ===' % len(samples))
for s in samples[:2]:
    h = s.get('heights_y') or []
    print('  axis=%s fixed=%s  n=%d' % (s.get('axis'), s.get('fixed_coordinate'), len(h)))
    print('    heights:', h)
    rises = s.get('rises_from_last_floor') or []
    print('    rises  :', rises)
    vals = [v for v in h if v is not None]
    if vals:
        print('    min=%s max=%s  none=%d' % (min(vals), max(vals), sum(1 for v in h if v is None)))
    print()

print('=== spike / null analysis across all sample lines ===')
total_null = total_spike = total_cells = 0
for s in samples:
    h = s.get('heights_y') or []
    vals = [v for v in h if v is not None]
    if len(vals) < 5:
        continue
    total_cells += len(h)
    total_null += sum(1 for v in h if v is None)
    for i in range(2, len(h) - 2):
        window = [h[j] for j in range(i - 2, i + 3) if h[j] is not None]
        if h[i] is None or len(window) < 5:
            continue
        neighbours = sorted(window)
        median = neighbours[len(neighbours) // 2]
        if h[i] - median >= 2:
            total_spike += 1
print('  sampled cells : %d' % total_cells)
print('  null columns  : %d  (%.1f%%)' % (total_null, 100 * total_null / max(1, total_cells)))
print('  spike columns : %d  (rises >=2 above local median)' % total_spike)
print()

print('=== are the spikes ISOLATED (chimney-like) or part of a broader run? ===')
for s in samples:
    h = s.get('heights_y') or []
    vals = [v for v in h if v is not None]
    if len(vals) < 5:
        continue
    spans = []
    i = 0
    while i < len(h):
        if h[i] is None:
            i += 1
            continue
        median = sorted(vals)[len(vals) // 2]
        if h[i] - median >= 2:
            j = i
            while j < len(h) and h[j] is not None and h[j] - median >= 2:
                j += 1
            spans.append((i, j - i, h[i]))
            i = j
        else:
            i += 1
    if spans:
        print('  axis=%s fixed=%-3s  raised spans (start,len,top): %s' % (s.get('axis'), s.get('fixed_coordinate'), spans))

print()
print('=== roof_column_map: how many columns stand above their neighbours? ===')
colmap = report.get('roof_column_map') or {}
grid = colmap.get('columns_z_x') or []
print('  grid rows=%d cols=%d start_xz=%s' % (len(grid), len(grid[0]) if grid else 0, colmap.get('start_xz')))
heights = []
for line in grid:
    heights.append([(c['top_y'] if c else None) for c in line])
flat = [v for line in heights for v in line if v is not None]
if flat:
    from collections import Counter
    common = Counter(flat).most_common(6)
    print('  most common top_y (roof surface is the mode):', common)
    mode = common[0][0] if common else None
    above = sum(1 for v in flat if mode is not None and v - mode >= 2)
    print('  columns >=2 above the modal surface: %d / %d (%.1f%%)  <- chimneys/crest, not roof'
          % (above, len(flat), 100 * above / len(flat)))
