# -*- coding: utf-8 -*-
"""Probe: what does each tier actually add to the built geometry?

Decisive question: if the facades (tier=1) gate demands window surrounds and a
cornice, tier 1 must build them.  Otherwise the gate is unsatisfiable and the
run can only spin.
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

from paris_builder import haussmann_reference as hr  # noqa: E402

RUN = os.path.join('runs', 'ATELIER-A9B3C7EE')
task = json.load(io.open(os.path.join(RUN, 'workflow.json'), encoding='utf-8'))
sel = task.get('selected') or {}
print('selected stages:', sorted(sel.keys()))
src = sel.get('facades') or sel.get('frameworks')
plan = src['plan']
print('plan:', json.dumps(plan, ensure_ascii=False))

pl = hr.plan_for(**plan) if hasattr(hr, 'plan_for') else None
if pl is None:
    from paris_builder import design
    pl = design.plan_for(**plan)
print('plan obj:', pl.describe() if hasattr(pl, 'describe') else pl)

BLOCKS = {'minecraft:air'}


def cells(scene):
    """Yield ((x,y,z), 'minecraft:name[state]') for every non-air cell."""
    vol = getattr(scene, 'volume', None)
    if vol is None:
        for key, block in scene.items():
            yield key, block
        return
    palette = scene.palette
    sy, sz, sx = vol.shape
    for y in range(sy):
        for z in range(sz):
            for x in range(sx):
                state = palette[int(vol[y, z, x])]
                name = state.split('[')[0]
                if name in ('minecraft:air', 'air'):
                    continue
                yield (x, y, z), state


counts = {}
scenes = {}
for tier in (0, 1, 2, 3):
    out = hr.build_corner(pl, tier=tier)
    scene = out[0] if isinstance(out, tuple) else out
    flat = dict(cells(scene))
    scenes[tier] = flat
    kinds = {}
    for block in flat.values():
        name = block.split('[')[0]
        kinds[name] = kinds.get(name, 0) + 1
    counts[tier] = (len(flat), kinds)
    print('tier %d: %d blocks, %d distinct' % (tier, len(flat), len(kinds)))

print()
print('=== tier 0 vs 1 ===')
t0, k0 = counts[0]
t1, k1 = counts[1]
print('added blocks: %+d' % (t1 - t0))
for name in sorted(set(k0) | set(k1)):
    a, b = k0.get(name, 0), k1.get(name, 0)
    if a != b:
        print('   %-42s %5d -> %5d  (%+d)' % (name, a, b, b - a))

print()
print('=== does tier 1 differ from tier 0 in ANY cell? ===')
s0, s1 = scenes[0], scenes[1]
diff = 0
for key in set(s0) | set(s1):
    if s0.get(key) != s1.get(key):
        diff += 1
print('differing cells:', diff)

print()
print('=== keyword probe for facade vocabulary in tier 1 block names ===')
vocab = ('stair', 'slab', 'wall', 'pane', 'bars', 'fence', 'iron', 'trapdoor',
         'chain', 'lantern', 'flower', 'carpet', 'sign', 'button', 'lever',
         'grindstone', 'anvil', 'cauldron', 'hopper', 'stonecutter')
for tier in (0, 1):
    _, kinds = counts[tier]
    hits = sorted(n for n in kinds if any(v in n for v in vocab))
    print('tier %d vocabulary blocks (%d):' % (tier, len(hits)))
    for n in hits:
        print('    %-46s %5d' % (n, kinds[n]))
