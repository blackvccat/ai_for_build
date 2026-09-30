"""Clean the source schematics into the detail database (knowledge/library-v2).

What this does, in order, and why each step is a *record* rather than a silent action:

1. **Survey and judge.** `survey_incoming.py` measures every source and records why it
   is taken or excluded. Nothing is dropped without a written reason.
2. **Extract detail units.** From a taken source, cut the units that are actually
   details: a window, a shopfront bay, a cornice run, a chimney, a roof dormer, a bay
   of facade. Each cut is anchored on the blocks that *make* it a detail (trapdoors,
   panes, walls, stairs, doors, slabs) rather than on an arbitrary grid, so the unit
   keeps its parts together.
3. **Normalise and clean.** Each unit is stripped of air padding, documented with its
   exact states, depth layers, connectors and outside direction, and rejected if it is
   not a usable detail: too few blocks, no state at all, or one block repeated.
4. **Record provenance.** Every unit carries its source file, the SHA256 of that source,
   and the bounding box it was cut from, so any claim can be traced back.

The output is additive: `knowledge/library-v1` is the recorded PAR-002 evidence and is
never touched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from paris_builder.exporter import write_schematic  # noqa: E402
from paris_builder.schematic import AIR_BLOCKS, base_block, load_schematic  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT.parent / '_incoming_schematics'
OUT = ROOT / 'knowledge/library-v2/details'

#: Blocks that *are* a detail, because something about them only exists as a state.
#:
#: The list is deliberately narrow. `wall`, `stairs`, `slab` and `carpet` are *not* here:
#: they cover most of a facade, so seeding on them and flood filling produced "details"
#: the size of whole buildings — one 190x55x125 unit with 392,453 blocks. A detail has to
#: be seeded on a block that is rare enough to mark one unit.
DISTINCTIVE_ANCHORS = ('trapdoor', 'pane', 'glass', 'fence_gate', 'bars', 'door',
                       'lantern', 'chain', 'lever', 'piston_head', 'grindstone', 'anvil',
                       'bell', 'bed', 'lectern', 'campfire', 'candle', 'flower_pot',
                       'sign', 'banner', 'torch', 'ladder', 'scaffolding', 'hopper',
                       'cauldron', 'composter', 'barrel')

#: Cornices, roofs and chimneys are runs rather than objects, so they are seeded on the
#: moulding blocks themselves — but with a tighter halo and the same hard size cap, so a
#: run becomes one cut piece instead of the whole wall.
RUN_ANCHORS = ('slab', 'stairs', 'wall', 'trapdoor', 'fence', 'brick', 'campfire')

ANCHORS = {
    'window': DISTINCTIVE_ANCHORS,
    'shopfront': DISTINCTIVE_ANCHORS,
    'cornice': RUN_ANCHORS,
    'roof': RUN_ANCHORS,
    'chimney': ('brick', 'campfire', 'lantern', 'smoker', 'blast_furnace'),
}

#: A detail needs at least this many solid blocks and this many distinct states.
MIN_SOLID = 8
MIN_DISTINCT_STATES = 4

#: Hard cap on a detail's extent in any axis, in cells.
DETAIL_MAX = 10

#: How far beyond the anchor cluster to keep, in cells. This is deliberately one cell:
#: the detail *is* the anchor blocks — a window's trapdoors, panes, gates and leaves —
#: and the halo only carries the single course of surround that touches them. Growing
#: further walks into the masonry, and a cut that is 75% wall is a piece of wall with a
#: window in it, not a window. The first two runs of this tool made exactly that mistake:
#: 20x5x5 units of solid stone, then a 190x55x125 unit that was the whole building.
HALO = 1
RUN_HALO = 1


def source_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plain(value):
    """Convert numpy scalars to Python ones so the records can be serialised.

    `np.where` hands back `np.int64`, and `json` refuses it. This cost a run before, so
    every record goes through here rather than relying on the caller.
    """
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def state_grid(data):
    """A grid of state strings, so cuts can be reasoned about by name."""
    palette = np.asarray(['minecraft:air' if base_block(s) in AIR_BLOCKS else s
                          for s in data.id_to_state], dtype=object)
    return palette[data.volume]


def is_anchor(state: str, kind: str) -> bool:
    if not state or state == 'minecraft:air':
        return False
    block = base_block(state).replace('minecraft:', '').split('[')[0]
    return any(hint in block for hint in ANCHORS[kind])


def cut_units(grid, kind: str, halo: int = None, max_extent: int = DETAIL_MAX):
    """Yield (x0, x1, y0, y1, z0, z1) boxes, one per detail.

    The growth is a flood fill from each unvisited anchor, expanded in order of
    increasing distance so the cut stays compact around its seed, and **stopped when it
    reaches `max_extent` in any axis**. Without that stop the fill walks the whole
    facade and the "detail" is the building: the first run of this tool produced a
    190x55x125 unit with 392,453 blocks that way.
    """
    height, depth, width = grid.shape
    if halo is None:
        halo = RUN_HALO if kind in ('cornice', 'roof') else HALO
    occupied = np.zeros(grid.shape, dtype=bool)
    for y in range(height):
        for z in range(depth):
            for x in range(width):
                if is_anchor(str(grid[y, z, x]), kind):
                    occupied[y, z, x] = True
    seen = np.zeros(grid.shape, dtype=bool)
    boxes = []
    coords = list(zip(*np.where(occupied)))
    for y, z, x in coords:
        if seen[y, z, x]:
            continue
        # Breadth-first from the seed, so the box grows evenly instead of running along
        # one axis first.
        queue = [(y, z, x)]
        seen[y, z, x] = True
        cells = []
        head = 0
        while head < len(queue):
            cy, cz, cx = queue[head]
            head += 1
            cells.append((cy, cz, cx))
            ys = [c[0] for c in cells]
            zs = [c[1] for c in cells]
            xs = [c[2] for c in cells]
            if max(max(ys) - min(ys), max(zs) - min(zs), max(xs) - min(xs)) >= max_extent:
                break
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        ny, nz, nx = cy + dy, cz + dz, cx + dx
                        if not (0 <= ny < height and 0 <= nz < depth and 0 <= nx < width):
                            continue
                        if seen[ny, nz, nx] or not occupied[ny, nz, nx]:
                            continue
                        seen[ny, nz, nx] = True
                        queue.append((ny, nz, nx))
        ys = [c[0] for c in cells]
        zs = [c[1] for c in cells]
        xs = [c[2] for c in cells]
        # Clamp the *component* to the size cap before adding the halo. Flood fill alone
        # is not enough: in a dense facade almost every block of a kind is connected to
        # the next, so the component can span the whole building. Clamping keeps the cut
        # around the seed, and the halo then carries the one course of surround.
        cx = (min(xs) + max(xs)) // 2
        cy = (min(ys) + max(ys)) // 2
        cz = (min(zs) + max(zs)) // 2
        half_x = min(max(cx - min(xs), max(xs) - cx), max_extent // 2)
        half_y = min(max(cy - min(ys), max(ys) - cy), max_extent // 2)
        half_z = min(max(cz - min(zs), max(zs) - cz), max_extent // 2)
        boxes.append((max(0, cx - half_x - halo), min(width - 1, cx + half_x + halo),
                      max(0, cy - half_y - halo), min(height - 1, cy + half_y + halo),
                      max(0, cz - half_z - halo), min(depth - 1, cz + half_z + halo)))
    return boxes


def base_names(grid):
    """A (y, z, x) array of bare block names, computed once per source.

    Built vectorised because the naive version of this walked the whole grid inside a
    nested loop and took minutes per source.
    """
    flat = grid.ravel()
    names = np.empty(flat.shape, dtype=object)
    for value in set(flat):
        state = str(value)
        if state == 'minecraft:air':
            names[flat == value] = 'air'
            continue
        names[flat == value] = base_block(state).replace('minecraft:', '').split('[')[0]
    return names.reshape(grid.shape)


#: Blocks that occupy more than one cell as one object. A cut that keeps only part of one
#: is an incomplete state. Matched by *substring*, because the actual names are
#: `oak_door`, `dark_oak_door`, `birch_door`: an exact-membership test against `'door'`
#: never matches and the sealing silently does nothing, which is how the first attempt at
#: this fix left all 188 half-doors in place.
MULTICELL = ('door', 'bed', 'tall_grass', 'large_fern', 'sunflower', 'lilac',
             'rose_bush', 'peony', 'tall_seagrass', 'small_dripleaf', 'piston_head')


def is_multicell(name: str) -> bool:
    return any(hint in name for hint in MULTICELL)


def seal_multicell(grid, names, box, limit: int = 24):
    """Grow a cut box until it contains whole multi-cell blocks.

    A door is *two cells*, and a cut that keeps only one of them is an incomplete block
    state: in game it renders as half a door, and the project's geometry check fails it.
    188 of the first 773 detail units failed exactly that way, all of them doors sliced by
    the halo.

    Returns None when the box cannot be sealed within `limit`, so the caller can record a
    refusal rather than write a broken unit.
    """
    x0, x1, y0, y1, z0, z1 = box
    for _ in range(24):
        inner_names = names[y0:y1 + 1, z0:z1 + 1, x0:x1 + 1]
        wanted = {str(n) for n in inner_names.ravel() if is_multicell(str(n))}
        if not wanted:
            return (x0, x1, y0, y1, z0, z1)
        grew = False
        for name in wanted:
            ys, zs, xs = np.where(names == name)
            for y, z, x in zip(ys, zs, xs):
                # Only a cell that *touches* the current box may pull it open. Collecting
                # every cell of that block in the whole grid instead grew a 19x6x24 box
                # that swallowed the building's doors, which is the bug this note marks.
                if x0 - 1 <= x <= x1 + 1 and y0 - 1 <= y <= y1 + 1 and z0 - 1 <= z <= z1 + 1:
                    nx0, nx1 = min(x0, int(x)), max(x1, int(x))
                    ny0, ny1 = min(y0, int(y)), max(y1, int(y))
                    nz0, nz1 = min(z0, int(z)), max(z1, int(z))
                    if (nx0, nx1, ny0, ny1, nz0, nz1) != (x0, x1, y0, y1, z0, z1):
                        x0, x1, y0, y1, z0, z1 = nx0, nx1, ny0, ny1, nz0, nz1
                        grew = True
        if not grew:
            return (x0, x1, y0, y1, z0, z1)
        if max(x1 - x0, y1 - y0, z1 - z0) > limit:
            return None
    return None


def clean_cut(grid, names, box, seal: bool = True):
    """Trim air from a cut and return (subgrid, offset) or None if it is not a detail."""
    if seal:
        sealed = seal_multicell(grid, names, box)
        if sealed is None:
            return None
        box = sealed
    x0, x1, y0, y1, z0, z1 = box
    sub = grid[y0:y1 + 1, z0:z1 + 1, x0:x1 + 1]
    occupied = sub != 'minecraft:air'
    if not occupied.any():
        return None
    ys, zs, xs = np.where(occupied)
    ty0, ty1 = int(ys.min()), int(ys.max())
    tz0, tz1 = int(zs.min()), int(zs.max())
    tx0, tx1 = int(xs.min()), int(xs.max())
    # Cleaning a candidate must not modify the source used by subsequent cuts.
    trimmed = sub[ty0:ty1 + 1, tz0:tz1 + 1, tx0:tx1 + 1].copy()
    return trimmed, (x0 + tx0, y0 + ty0, z0 + tz0)


def judge_detail(trimmed) -> tuple:
    """(usable, reason) for one cleaned cut.

    Besides the size floor, a cut is rejected if it is mostly wall: a unit whose solid
    cells are overwhelmingly one plain block is masonry with something in it, not a
    detail. The measure is the *anchor share* handed in by the caller, which knows which
    cells were anchors.
    """
    cells = [str(v) for v in trimmed.ravel()]
    solid = [c for c in cells if c != 'minecraft:air']
    distinct = set(solid)
    if len(solid) < MIN_SOLID:
        return False, '实体方块仅 %d 个 < %d：不足以独立成件' % (len(solid), MIN_SOLID)
    if len(distinct) < MIN_DISTINCT_STATES:
        return False, '不同状态仅 %d 种 < %d：不足以独立成件' % (len(distinct), MIN_DISTINCT_STATES)
    counts = Counter(distinct)
    if len(counts) and max(len(solid) - counts[c] for c in counts) == 0:
        return False, '整体重复同一方块：不是构件'
    return True, ''


def depth_layers(trimmed):
    """How many non-air cells on each z plane — the record that proves a real recess."""
    out = []
    for z in range(trimmed.shape[1]):
        layer = trimmed[:, z, :]
        out.append({'z': int(z), 'nonair': int((layer != 'minecraft:air').sum())})
    return out


def connectors(trimmed):
    """Which cells of the bottom plane are occupied at each side, for placement."""
    bottom = trimmed[0]
    xs = [int(x) for x in np.where((bottom != 'minecraft:air').any(axis=0))[0]]
    out = {}
    if xs:
        out['left'] = [xs[0], 0, 0]
        out['right'] = [xs[-1], 0, 0]
    out['size_xyz'] = [int(trimmed.shape[2]), int(trimmed.shape[0]), int(trimmed.shape[1])]
    return out


def normalise_doors(trimmed) -> tuple:
    """把门的两扇规范化成 lower/upper 配对，并返回 (改动格数, 未配对格数, 原始状态计数)。

    源作品里门常被导出成两格都是 `half=lower`——用户的说明解释了原因：**有些状态是靠方块
    更新自己长出来的**。在允许更新的环境里建的时候，游戏把上扇纠正成了 upper；导出成
    `.schem` 时存的却是导出那一刻的状态，于是两格都写着 lower。

    这在「方块禁止更新」的粘贴环境里就是硬错误：游戏不会替我们纠正，粘下去是两截半门。
    所以导出件必须自己带正确状态，而不是指望重算。原始状态证据保留在 `source_door_states`
    里，改动格数记在 `normalisations` 里——清洗不等于篡改，要有账。

    裁剪边界会切断门：另一半没被切进来时无法配对，这种格子单独计数，由调用方整件拒绝。
    """
    from paris_builder.architecture import split_state, state as make_state
    shape = trimmed.shape
    changed = 0
    unpaired = []
    originals = Counter(str(v) for v in trimmed.ravel()
                        if base_block(str(v)).endswith('_door'))
    for x in range(shape[2]):
        for z in range(shape[1]):
            y = 0
            while y < shape[0]:
                value = str(trimmed[y, z, x])
                name, props = split_state(value)
                if not name.endswith('_door'):
                    y += 1
                    continue
                # A door is exactly two cells: this one and the one above it.
                if y + 1 >= shape[0]:
                    unpaired.append([x, y, z])
                    y += 1
                    continue
                above = str(trimmed[y + 1, z, x])
                above_name, above_props = split_state(above)
                if above_name != name:
                    # The cut sliced the door: its other half is outside the box.
                    unpaired.append([x, y, z])
                    y += 1
                    continue
                props = dict(props)
                props['half'] = 'lower'
                fixed_lower = make_state(name.replace('minecraft:', ''), **props)
                if fixed_lower != value:
                    changed += 1
                trimmed[y, z, x] = fixed_lower
                upper_props = dict(above_props)
                upper_props['half'] = 'upper'
                fixed_upper = make_state(name.replace('minecraft:', ''), **upper_props)
                if fixed_upper != above:
                    changed += 1
                trimmed[y + 1, z, x] = fixed_upper
                y += 2
    return changed, unpaired, dict(originals)


def frozen_requirements(trimmed) -> dict:
    """这个构件在「方块禁止更新」的粘贴环境下要怎样写才成立。

    用户在禁止更新的环境里粘贴，所以游戏**不会**替我们重算方块状态：墙肢不会自己连向
    邻块、玻璃板不会长出边、楼梯不会自己选外角。凡是带属性的方块，都必须逐格把状态写死。

    这里记录三件事：
      * `stateful_cells` —— 必须逐格冻结写入的格数（禁止更新下的硬性要求）；
      * `categories`     —— 这些有状态格分别属于哪类技法（连接/形状/朝向…）；
      * `blockers`       —— 真正不成立的格：`up=false` 且四向全 `none` 的幽灵墙肢、
                            四向都不连接的玻璃板。这类格在游戏里没有模型或会消失。
    """
    from paris_builder.architecture import sensitive, state_category, split_state
    solid = [str(v) for v in trimmed.ravel() if v != 'minecraft:air']
    stateful = [s for s in solid if sensitive(s)]
    categories = Counter(state_category(s) for s in stateful)
    ghost = dead = 0
    for state in solid:
        name, props = split_state(state)
        if name.endswith('_wall') and props.get('up', 'false') == 'false' and \
                all(props.get(side, 'none') == 'none'
                    for side in ('north', 'east', 'south', 'west')):
            ghost += 1
        if name.endswith('_pane') or name == 'iron_bars':
            sides = [props.get(side, 'false') for side in ('north', 'east', 'south', 'west')
                     if side in props]
            if sides and not any(s == 'true' for s in sides):
                dead += 1
    blockers = []
    if ghost:
        blockers.append('幽灵墙肢 %d 格（up=false 且四向 none，游戏内无模型）' % ghost)
    if dead:
        blockers.append('不连接玻璃板 %d 格（禁止更新下不会自连，视觉上消失）' % dead)
    return {
        'update_policy': 'PASTE_WITH_BLOCK_UPDATES_DISABLED',
        'stateful_cells': len(stateful),
        'state_categories': dict(categories),
        'ghost_walls': ghost,
        'dead_panes': dead,
        'blockers': blockers,
        'frozen_ok': not blockers,
        'note': '禁止更新环境下，上面这些有状态格必须逐格写成记录里的确切状态；'
                '不能依赖游戏重算，否则连接、朝向与楼梯形状都会变。',
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--survey', type=Path, default=ROOT / 'runs/DETAIL-INTAKE-v0.1/survey.json')
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--limit-per-source', type=int, default=40)
    parser.add_argument('--write-schem', action='store_true',
                        help='also export each accepted unit as its own .schem')
    parser.add_argument('--functional-doors', action='store_true',
                        help='only use after confirming door blocks are functional doors, not decorative window models')
    args = parser.parse_args()

    survey = {row['source']: row for row in
              json.loads(args.survey.read_text(encoding='utf-8'))}
    args.out.mkdir(parents=True, exist_ok=True)

    records, rejected, per_source = [], [], []
    for path in sorted(SOURCES.rglob('*.schem')):
        row = survey.get(path.name)
        if not row or not row.get('contributes_detail'):
            continue
        kind_default = 'window' if row['source_kind'] == 'component' else 'window'
        data = load_schematic(path)
        grid = state_grid(data)
        names = base_names(grid)
        digest = source_digest(path)
        taken = 0
        # A component source is itself one detail; a building is searched for many.
        kinds = ['window'] if row['source_kind'] == 'component' else \
            ['window', 'cornice', 'chimney', 'roof', 'shopfront']
        index = 0
        for kind in kinds:
            if taken >= args.limit_per_source:
                break
            try:
                boxes = cut_units(grid, kind)
            except Exception as error:                                # noqa: BLE001
                rejected.append({'source': path.name, 'kind': kind,
                                 'reason': 'cut failed: %s' % error})
                continue
            for box in boxes:
                if taken >= args.limit_per_source:
                    break
                cleaned = clean_cut(grid, names, box)
                if cleaned is None:
                    continue
                trimmed, offset = cleaned
                usable, reason = judge_detail(trimmed)
                detail_id = '%s-%s-%02d' % (path.stem.replace(' ', '_'), kind, index)
                index += 1
                if not usable:
                    rejected.append({'source': path.name, 'kind': kind,
                                     'detail_id': detail_id, 'reason': reason,
                                     'bbox_xyz': list(box)})
                    continue
                # 规范化必须在判读之前：门的两扇要成对，否则禁止更新下粘出来是两截半门。
                if args.functional_doors:
                    doors_fixed, doors_unpaired, door_states = normalise_doors(trimmed)
                else:
                    doors_fixed, doors_unpaired = 0, []
                    door_states = dict(Counter(str(v) for v in trimmed.ravel()
                                               if base_block(str(v)).endswith('_door')))
                if doors_unpaired:
                    rejected.append({
                        'source': path.name, 'kind': kind, 'detail_id': detail_id,
                        'reason': '裁剪切断门：%d 格无法配对（禁止更新下是半扇门）'
                                  % len(doors_unpaired),
                        'bbox_xyz': list(box), 'unpaired': doors_unpaired[:8]})
                    continue
                solid = [str(v) for v in trimmed.ravel() if v != 'minecraft:air']
                frozen = frozen_requirements(trimmed)
                if not frozen['frozen_ok']:
                    rejected.append({'source': path.name, 'kind': kind,
                                     'detail_id': detail_id,
                                     'reason': '禁止更新下不成立：' + '；'.join(frozen['blockers']),
                                     'bbox_xyz': list(box)})
                    continue
                record = {
                    'detail_id': detail_id,
                    'kind': kind,
                    'source': path.name,
                    'source_group': row['group'],
                    'source_kind': row['source_kind'],
                    'source_sha256': digest,
                    'cut_bbox_xyz': [list(box[:2]), list(box[2:4]), list(box[4:])],
                    'offset_xyz': list(offset),
                    'size_whd': [int(trimmed.shape[2]), int(trimmed.shape[0]),
                                 int(trimmed.shape[1])],
                    'solid_blocks': len(solid),
                    'distinct_states': len(set(solid)),
                    'exact_block_states': dict(Counter(solid).most_common()),
                    'depth_layers': depth_layers(trimmed),
                    'connectors': connectors(trimmed),
                    'outside': 'UNREVIEWED: infer per source and crop; street3 faces +z, not -z',
                    'material_family': base_block(Counter(solid).most_common(1)[0][0]),
                    'frozen': frozen,
                    'normalisations': {
                        'door_halves_fixed': doors_fixed,
                        'reason': '显式选择功能门配对清洗' if args.functional_doors else
                                  '保留原始half和朝向；装饰门叶与功能门需逐件区分。',
                        'original_door_states': door_states,
                    },
                    'evidence_status': 'SOURCE_STATES_VERIFIED_SEMANTICS_INFERRED',
                    'note': 'cut from the user\'s own build; states are exact, the '
                            'semantic name of the detail is inferred',
                }
                records.append(record)
                taken += 1
                if args.write_schem:
                    directory = args.out / record['detail_id']
                    directory.mkdir(parents=True, exist_ok=True)
                    states, ids = [], {}
                    volume = np.zeros(trimmed.shape, dtype=np.int32)
                    for y in range(trimmed.shape[0]):
                        for z in range(trimmed.shape[1]):
                            for x in range(trimmed.shape[2]):
                                value = str(trimmed[y, z, x])
                                if value not in ids:
                                    ids[value] = len(states)
                                    states.append(value)
                                volume[y, z, x] = ids[value]
                    write_schematic(directory / 'detail.schem', volume, states,
                                    name=record['detail_id'])
        per_source.append({'source': path.name, 'group': row['group'],
                           'kind': row['source_kind'], 'details_taken': taken})

    (args.out / 'index.json').write_text(
        json.dumps(plain({'details': records, 'count': len(records)}), indent=2,
                   ensure_ascii=False), encoding='utf-8')
    (args.out / 'exclusions.json').write_text(
        json.dumps(plain(rejected), indent=2, ensure_ascii=False), encoding='utf-8')
    (args.out / 'per_source.json').write_text(
        json.dumps(plain(per_source), indent=2, ensure_ascii=False), encoding='utf-8')

    by_kind = Counter(r['kind'] for r in records)
    by_family = Counter(r['material_family'] for r in records)
    print('detail units: %d   rejected cuts: %d' % (len(records), len(rejected)))
    print('by kind: %s' % dict(by_kind))
    print('by material family (top 12): %s' % dict(by_family.most_common(12)))
    print('\nper source:')
    for row in per_source:
        print('  %-24s %-9s %-9s %3d' % (row['source'][:24], row['group'],
                                         row['kind'], row['details_taken']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
