"""Cluster the mined bay units by dominant material so a building can lock one family.

The first attempt stamped a random unit per opening and the facades came out
patchy: one bay in red terracotta, the next in pale sandstone, the next with green
ironwork. Real Haussmann facades keep one stone family with small variations, so
generation needs a family lock rather than free sampling. This tool reports what
families actually exist in the mined library.
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from paris_builder.source_bays import dominant_state, unit_family  # noqa: E402

recipes = json.loads((ROOT / 'knowledge/library-v1/source-bays/recipes.json').read_text(encoding='utf-8'))

grouped = defaultdict(list)
for unit in recipes:
    family = unit_family(unit)
    grouped[family].append((unit, dominant_state(unit)))

print('mined units: %d' % len(recipes))
print()
print('%-14s %5s  %s' % ('family', 'units', 'dominant block examples'))
for family, items in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
    examples = Counter(name for _, name in items).most_common(3)
    print('%-14s %5d  %s' % (family, len(items), ', '.join('%s x%d' % (n, c) for n, c in examples)))

print()
print('width x family coverage (a family is only usable if it has units per bay width):')
by_width = defaultdict(Counter)
for family, items in grouped.items():
    for unit, _ in items:
        by_width[unit['dimensions_wdh'][0]][family] += 1
for width in sorted(by_width):
    print('  width %d : %s' % (width, dict(by_width[width].most_common(5))))
