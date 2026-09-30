"""Print what is actually in the retrieval index versus what was scanned.

Read-only survey used to explain the pipeline honestly to the user.
"""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
meta = json.loads((root / 'knowledge/retrieval/manifest.json').read_text(encoding='utf-8'))
cov = json.loads((root / 'knowledge/library-v1/exhaustive-contexts/coverage.json').read_text(encoding='utf-8'))
cat = json.loads((root / 'knowledge/library-v1/catalog.json').read_text(encoding='utf-8'))

print('=== retrieval index (what the model can actually query) ===')
print('  entries          :', meta['count'])
print('  semantic dim     :', meta['semantic_dimension'])
print('  encoder          :', meta['model'])
print('  excluded         :', meta.get('excluded'))
print('  admission        :', meta.get('admission'))

print()
print('=== 14 source schematics: local scan ===')
print('  sources          :', len(cov['sources']))
print('  non-air positions:', sum(s['nonair_positions_scanned'] for s in cov['sources']))
print('  unique contexts  :', cov['unique_contexts'])
print('  semantic scope   :', cov['semantic_exhaustiveness'])

print()
print('=== component library ===')
print('  annotated windows:', len(cat['windows']))
print('  placeable recipes:', len(cat['recipes']))
print('  recipe families  :', len(set(r['family'] for r in cat['recipes'])))

print()
print('=== who is embedded vs who is only indexed ===')
embedded = {r.get('component_id') or r.get('id') for r in cat['windows']}
embedded |= {r.get('component_id') or r.get('id') for r in cat['recipes']}
embedded.discard(None)
print('  embedded ids     :', len(embedded))
print('  unique contexts  :', cov['unique_contexts'], '(stored in SQLite with evidence, NOT embedded as vectors)')
