"""判读一批细节构件在「方块禁止更新」的粘贴环境下是否成立。

为什么必须单独做这一步
----------------------
方块更新会重算方块的状态：墙肢会连向邻块、玻璃板会长出色边、楼梯会自己选外角。用户在
**禁止更新**的环境里粘贴，所以这些重算不会发生——结果是：源作品里「靠更新长出来」的手法，
如果直接把最终状态抄过来，粘下去就是错的。

更糟的一种情况是「幽灵方块」：`up=false` 且四向都不连接的墙肢，游戏里根本没有模型，
看起来像墙，实际上是空的。项目早先已经吃过这个亏。

判据（来自项目既有约定）
------------------------
- 有属性的方块（`sensitive()`）→ 禁止更新时必须**逐格冻结写入**，不能指望重算；
- 墙肢 `up=false` 且四向全 `none` → 幽灵方块，必须拒绝或改状态；
- 玻璃板四向全 `false` → 不连接，视觉上会消失；
- 楼梯如果 `shape` 与几何不符 → 禁止更新时不会被纠正，保持错误形状。

这个工具只做判读和记录，不改状态：怎么修是设计决定，得先看清有多少、是哪些。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from paris_builder.architecture import sensitive, state_category, split_state  # noqa: E402
from paris_builder.schematic import load_schematic  # noqa: E402

#: 墙肢：up=false 且四向都 none 是幽灵方块，游戏里没有模型。
WALL_SIDES = ('north', 'east', 'south', 'west')


def states_of(data) -> Counter:
    counts = Counter()
    volume = data.volume
    for palette_id in range(1, len(data.id_to_state)):
        state = data.id_to_state[palette_id]
        if not state or state == 'minecraft:air':
            continue
        n = int((volume == palette_id).sum())
        if n:
            counts[state] = n
    return counts


def ghost_wall(state: str) -> bool:
    name, props = split_state(state)
    if not name.endswith('_wall'):
        return False
    if props.get('up', 'false') != 'false':
        return False
    return all(props.get(side, 'none') == 'none' for side in WALL_SIDES)


def dead_pane(state: str) -> bool:
    name, props = split_state(state)
    if not (name.endswith('_pane') or name == 'iron_bars'):
        return False
    sides = [props.get(side, 'false') for side in WALL_SIDES if side in props]
    return bool(sides) and not any(s == 'true' for s in sides)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path, nargs='?',
                        default=Path(__file__).resolve().parents[1] / 'knowledge/library-v2/details')
    parser.add_argument('--json', type=Path, default=None)
    parser.add_argument('--list-bad', type=int, default=8)
    args = parser.parse_args()

    rows = []
    totals = Counter()
    for schem in sorted(args.root.rglob('detail.schem')):
        data = load_schematic(schem)
        counts = states_of(data)
        row = {
            'detail_id': schem.parent.name,
            'cells': int(sum(counts.values())),
            'distinct_states': len(counts),
            'stateful_cells': sum(n for s, n in counts.items() if sensitive(s)),
            'categories': dict(Counter(state_category(s) for s in counts)),
            'ghost_walls': sum(n for s, n in counts.items() if ghost_wall(s)),
            'dead_panes': sum(n for s, n in counts.items() if dead_pane(s)),
        }
        categories = set(row['categories'])
        blockers = []
        if row['ghost_walls']:
            blockers.append('幽灵墙肢 %d 格（up=false 且四向 none）' % row['ghost_walls'])
        if row['dead_panes']:
            blockers.append('不连接玻璃板 %d 格' % row['dead_panes'])
        row['update_blockers'] = blockers
        row['frozen_ok'] = not blockers
        # 禁止更新下，所有有属性方块都要逐格冻结写入，这是必然要求而不是缺陷。
        row['frozen_writes_required'] = row['stateful_cells']
        rows.append(row)
        totals['details'] += 1
        totals['frozen_ok' if row['frozen_ok'] else 'frozen_blocked'] += 1
        totals['stateful_cells'] += row['stateful_cells']
        totals['ghost_walls'] += row['ghost_walls']
        totals['dead_panes'] += row['dead_panes']

    print('判读 %d 件细节（禁止更新环境）' % totals['details'])
    print('  禁止更新下成立: %d   被阻塞: %d' % (totals['frozen_ok'], totals['frozen_blocked']))
    print('  需要逐格冻结写入的有状态格: %d' % totals['stateful_cells'])
    print('  幽灵墙肢合计: %d 格   不连接玻璃板合计: %d 格' % (totals['ghost_walls'], totals['dead_panes']))
    cat = Counter()
    for row in rows:
        cat.update(row['categories'])
    print('\n状态类别分布（整库）:')
    for name, n in cat.most_common(12):
        print('  %-22s %6d' % (name, n))

    bad = [r for r in rows if not r['frozen_ok']]
    if bad:
        print('\n被阻塞的构件（前 %d 件）:' % min(args.list_bad, len(bad)))
        for row in bad[:args.list_bad]:
            print('  %-34s %s' % (row['detail_id'][:34], '; '.join(row['update_blockers'])))

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({'details': rows, 'totals': dict(totals)},
                                        indent=2, ensure_ascii=False), encoding='utf-8')
        print('\nwritten: %s' % args.json)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
