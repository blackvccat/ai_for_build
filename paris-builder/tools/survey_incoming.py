"""Survey the incoming source schematics before any of them is cleaned into the library.

Every extraction decision has to be made on measurements, not on the file name. This
prints, for each source: envelope, non-air count, how many *distinct block states* it
uses, how much of it is stateful (a block whose state changes how it renders), how much
is non-vanilla (Create and other mods), and how much of the volume it fills.

These measurements guide surface inspection, not architectural quality. Air is
identified by its block name, never by palette ID. Dense or cube-based sources can
still have useful surface techniques. Modded states require explicit translation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from paris_builder.schematic import AIR_BLOCKS, load_schematic, base_block  # noqa: E402

#: Blocks whose appearance depends on their state. A source made of these has technique
#: in it; one made of plain cubes does not.
STATEFUL_HINTS = ('stairs', 'slab', 'wall', 'fence', 'pane', 'trapdoor', 'door', 'gate',
                  'bars', 'carpet', 'snow', 'chain', 'lantern', 'candle', 'rod',
                  'button', 'lever', 'repeater', 'comparator', 'rail', 'vine', 'coral',
                  'grindstone', 'bell', 'anvil', 'hopper', 'scaffolding', 'lightning_rod',
                  'dripstone', 'amethyst', 'pointed_dripstone', 'glow_lichen', 'mangrove')


def survey(path: Path) -> dict:
    data = load_schematic(path)
    nonair = data.nonair_mask()
    counts = Counter({s: n for s, n in data.exact_state_counts().items()
                      if base_block(s) not in AIR_BLOCKS})
    families = Counter()
    for state, count in counts.items():
        families[base_block(state)] += count
    stateful = sum(n for s, n in counts.items()
                   if any(h in s.split('[')[0] for h in STATEFUL_HINTS))
    modded = sum(n for s, n in counts.items() if not s.startswith('minecraft:'))
    block_entities = len(data.block_entities)
    return {
        'source': path.name,
        'group': path.parent.name,
        'envelope_whd': [data.width, data.height, data.length],
        'nonair': int(nonair.sum()),
        'fill_ratio': round(float(nonair.sum()) / nonair.size, 4),
        'distinct_states': len(counts),
        'distinct_blocks': len(families),
        'stateful_blocks': stateful,
        'stateful_ratio': round(stateful / max(1, int(nonair.sum())), 4),
        'modded_blocks': modded,
        'modded_ratio': round(modded / max(1, int(nonair.sum())), 4),
        'block_entities': block_entities,
        'top_blocks': [[s, n] for s, n in families.most_common(6)],
        'sha256_source': hashlib.sha256(path.read_bytes()).hexdigest(),
        'air_palette_ids': data.air_ids.tolist(),
    }


#: An envelope at or below this in every axis is one detail unit rather than a build.
COMPONENT_MAX = 8


def verdict(row: dict) -> tuple:
    """Return eligibility for inspection, not a judgement of learned technique.

    The old palette-zero assumption falsely labelled six detailed street sources
    as solid fill. Neither density nor state share is enough to exclude a facade.
    Empty sources are excluded; all other caveats remain explicit for crop review.
    """
    envelope_max = max(row['envelope_whd'])
    kind = 'component' if envelope_max <= COMPONENT_MAX else 'building'
    reasons, blocking = [], []

    if row['nonair'] == 0:
        blocking.append('源文件没有非空气方块')
    elif row['fill_ratio'] >= 0.95:
        reasons.append('填充率 %.3f：需检查外表层；体积填充率不能证明立面没有手法'
                       % row['fill_ratio'])
    elif kind == 'building' and row['stateful_ratio'] < 0.06:
        reasons.append('状态方块占比 %.3f：需复核材料、几何和层次；占比不作手法质量判定'
                       % row['stateful_ratio'])
    elif kind == 'component' and row['stateful_ratio'] < 0.15:
        reasons.append('状态方块占比 %.3f：需逐件检查形状与用途' % row['stateful_ratio'])

    if not blocking:
        if row['modded_ratio'] > 0.05:
            reasons.append('模组方块 %.1f%%：细节需逐条转译记录' % (100 * row['modded_ratio']))
        if row['block_entities']:
            reasons.append('含 %d 个方块实体：转译后行为不等价，只取外观'
                           % row['block_entities'])

    row['source_kind'] = kind
    row['envelope_max'] = envelope_max
    if blocking:
        reasons = blocking + reasons
    return not blocking, reasons


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=None)
    parser.add_argument('--json', type=Path, default=None)
    args = parser.parse_args()
    root = args.root or (Path(__file__).resolve().parents[1].parent / '_incoming_schematics')

    rows = []
    for path in sorted(root.rglob('*.schem')):
        try:
            row = survey(path)
        except Exception as error:                                    # noqa: BLE001
            rows.append({'source': path.name, 'group': path.parent.name,
                         'error': '%s: %s' % (type(error).__name__, error)})
            continue
        contributes, reasons = verdict(row)
        row['contributes_detail'] = contributes
        row['exclusion_reasons'] = reasons
        rows.append(row)

    print('%-26s %-9s %8s %7s %6s %6s %6s %6s' % (
        'source', 'group', 'nonair', 'fill', 'states', 'statefl', 'modded', 'take'))
    for row in rows:
        if 'error' in row:
            print('%-26s %-9s ERROR %s' % (row['source'], row['group'], row['error']))
            continue
        print('%-26s %-9s %8d %7.3f %6d %6.3f %6.3f %6s' % (
            row['source'], row['group'], row['nonair'], row['fill_ratio'],
            row['distinct_states'], row['stateful_ratio'], row['modded_ratio'],
            'yes' if row['contributes_detail'] else 'NO'))
        for reason in row['exclusion_reasons']:
            print('%-26s   - %s' % ('', reason))

    totals = Counter()
    for row in rows:
        if 'error' in row:
            totals['error'] += 1
            continue
        totals['total'] += 1
        totals['take' if row['contributes_detail'] else 'skip'] += 1
    print('\n%s' % dict(totals))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding='utf-8')
        print('written: %s' % args.json)


if __name__ == '__main__':
    main()
