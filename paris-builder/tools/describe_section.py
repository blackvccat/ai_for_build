"""Describe one mined section: is it a wall fragment or a roof fragment?"""
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

root = Path(__file__).resolve().parents[1]
sections = json.loads((root / 'knowledge/library-v1/source-sections/sections.json').read_text(encoding='utf-8'))
entry = next(s for s in sections if s['recipe_id'] == sys.argv[1]) if len(sys.argv) > 1 else sections[0]
width, depth, height = entry['dimensions_wdh']
print(entry['recipe_id'], 'w x d x h =', entry['dimensions_wdh'], '| occurrences', entry['occurrences'],
      '| bays', entry['bays'], '| source', entry['source'])
volume = np.full((height, depth, width), -1, dtype=np.int32)
for x, z, y, value in entry['voxels']:
    volume[y, z, x] = value
names = np.array(entry['palette'])
print()
print('per level: solid / aperture counts, and how many depth rows are used')
for y in range(height):
    row = volume[y]
    name_row = np.where(row >= 0, names[np.clip(row, 0, None)], '')
    solid = np.sum((name_row != '') & (name_row != 'minecraft:air'))
    air = np.sum(name_row == 'minecraft:air')
    depth_rows = len({z for z in range(depth) if (name_row[z] != '').any()})
    print('  y=%d solid=%3d air=%3d depth_rows=%d' % (y, solid, air, depth_rows))
print()
print('top blocks:', Counter(entry['palette']).most_common(6))
print()
for y in range(height - 1, -1, -1):
    print('y=%d' % y)
    for z in range(depth):
        print('   ' + ''.join('#' if volume[y, z, x] >= 0 and names[volume[y, z, x]] != 'minecraft:air'
                              else ('.' if volume[y, z, x] >= 0 else ' ') for x in range(width)))
