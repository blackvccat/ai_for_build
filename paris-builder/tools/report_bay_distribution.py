"""Distribution report for mined source bays: how repetitive are the sources?"""
import sys
sys.path.insert(0, 'src')
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

import numpy as np
from collections import Counter

import mine_source_bays as miner
from paris_builder.schematic import load_schematic

root = Path(__file__).resolve().parents[1]
sources = sorted((root.parent / '巴黎建筑素材').glob('*.schem'))
groups = Counter()
sizes = Counter()
for path in sources:
    src = load_schematic(path)
    names = miner.block_names(src)
    solid = ~np.isin(names, miner.AIR)
    for bay in miner.find_bays(src.volume, names, solid):
        digest, trimmed = miner.signature(bay['voxels'])
        groups[digest] += 1
        sizes[(trimmed.shape[2], trimmed.shape[1], trimmed.shape[0])] += 1

total = sum(groups.values())
print('bay cuts total      :', total)
print('distinct units      :', len(groups))
hist = Counter(min(v, 20) for v in groups.values())
print('occurrence histogram (20 = 20+):')
for k in sorted(hist):
    print('   %2d occurrences : %5d units' % (k, hist[k]))
print('units occurring >= 3 :', sum(1 for v in groups.values() if v >= 3))
print('units occurring >= 5 :', sum(1 for v in groups.values() if v >= 5))
print('most common unit size (w,d,h):', sizes.most_common(4))
