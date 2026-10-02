# -*- coding: utf-8 -*-
"""Did the facades actually start using debug-stick technique?

The user's in-game rejection of the delivered building was: "立面细节没运用调试棒手法"
- the facade details do not use block-state technique. A debug stick does nothing on a
plain full cube; it only matters for blocks that carry orientation or shape state
(stairs, slabs, walls, panes, fences, trapdoors, rails).

So measure exactly that, from the exported schematics, and compare the delivered
revision (72, rejected in game) with the repaired one (73).
"""
import io
import json
import os
import sys
from collections import Counter

sys.path.insert(0, 'src')

from paris_builder.schematic import load_schematic, base_block, AIR_BLOCKS  # noqa: E402

SHAPED = ('_stairs', '_slab', '_wall', '_pane', '_bars', '_fence', '_fence_gate',
          '_trapdoor', '_door', '_button', '_lever', '_carpet', '_chain', '_lantern',
          '_grindstone', '_anvil', '_hopper', '_cauldron', '_sign', '_banner',
          '_candle', '_bed', '_ladder', '_scaffolding', '_lightning_rod')
#: Blocks whose default state already means something; a non-default value proves the
#: builder set a state on purpose rather than dropping a plain cube.
ORIENTED = ('facing=', 'half=', 'shape=', 'axis=', 'north=', 'east=', 'south=', 'west=',
            'up=', 'type=', 'open=', 'powered=', 'rotation=', 'hinge=', 'waterlogged=')


def profile(path, label):
    s = load_schematic(path)
    states = getattr(s, 'id_to_state', None) or s.palette
    volume = s.volume
    counts = Counter()
    total = 0
    shaped_cells = 0
    stateful_cells = 0
    for index, count in zip(*__import__('numpy').unique(volume, return_counts=True)):
        index = int(index)
        state = states[index] if not isinstance(states, dict) else states.get(index, states.get(str(index)))
        if state is None:
            continue
        name = base_block(state)
        if name in AIR_BLOCKS:
            continue
        total += count
        counts[name] += count
        if name.endswith(SHAPED):
            shaped_cells += count
            if any(token in state for token in ORIENTED):
                stateful_cells += count
    print('=== %s ===' % label)
    print('  file            : %s' % path)
    print('  非空气格        : %d' % total)
    print('  方块种类        : %d' % len(counts))
    print('  异形件格数      : %d  (%.1f%%)  <- stairs/slab/wall/pane/fence/trapdoor…'
          % (shaped_cells, 100.0 * shaped_cells / max(1, total)))
    print('  显式状态格数    : %d  (%.1f%% of 异形件)'
          % (stateful_cells, 100.0 * stateful_cells / max(1, shaped_cells)))
    print('  异形件种类 top12:')
    for name, count in Counter({n: c for n, c in counts.items() if n.endswith(SHAPED)}).most_common(12):
        print('      %-42s %5d' % (name, count))
    return {'total': total, 'shaped': shaped_cells, 'stateful': stateful_cells,
            'kinds': len(counts)}


targets = [
    ('runs/ATELIER-A9B3C7EE/revision-72/delivery/candidate.schem',
     'rev 72 — 交付版，用户游戏内否决("没用调试棒手法")'),
    ('runs/ATELIER-A9B3C7EE/revision-73/tier3/selected/candidate.schem',
     'rev 73 — source-state 修复后（待评审）'),
]
results = []
for path, label in targets:
    if os.path.isfile(path):
        results.append(profile(path, label))
        print()
    else:
        print('missing: %s' % path)

if len(results) == 2:
    a, b = results
    print('=== 修复前后对比 ===')
    print('  异形件: %d -> %d  (%+.1f 个百分点)'
          % (a['shaped'], b['shaped'],
             100.0 * b['shaped'] / max(1, b['total']) - 100.0 * a['shaped'] / max(1, a['total'])))
    print('  显式状态: %d -> %d' % (a['stateful'], b['stateful']))
    print('  方块种类: %d -> %d' % (a['kinds'], b['kinds']))

print()
print('=== rev73 manifest 的 source_state_audit ===')
m = 'runs/ATELIER-A9B3C7EE/revision-73/tier3/selected/generation_manifest.json'
if os.path.isfile(m):
    manifest = json.load(io.open(m, encoding='utf-8'))
    for key in ('source_state_audit', 'source_state_requirements', 'stamp_audit'):
        if key in manifest:
            print('  %s: %s' % (key, json.dumps(manifest[key], ensure_ascii=False)[:400]))
