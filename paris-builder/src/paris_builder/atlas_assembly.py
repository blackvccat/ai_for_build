"""库件组装引擎（手法图谱第④步）：用真人工件组装建筑，细节层不再是程序画符号。

设计依据（reports/TECHNIQUE_ATLAS_STUDY.md §6）：
- 件 = knowledge/library-v4/atlas-techniques 的人工裁件，状态随件携带，粘贴禁更新。
- 竖向叠放按件 record 的源 y 区间（源相对叠放，同 tools/build_part_prototype.py）。
- 旋转必须位置与状态一起转（transform_point + transform_state 同源约定）；
  technique_library.stamp 只转状态不动位置，故旋转件先派生（rotate）再以 turns=0 落位，
  审计用派生件逐格回读，与 verify_stamp_audit 的坐标约定完全一致。
- 含 create 模组壁柱的件（record.compatible_vanilla=false）不进装配；
  同元素用 vanilla 派生件替代（修补白色墙类 / 重裁干净剖条），逐件入账。
"""
from __future__ import annotations

import json
import hashlib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import technique_library as library
from .architecture import Scene, split_state, state, transform_point, transform_state
from .exporter import write_schematic
from .fonts import node_binary
from .schematic import load_schematic

ROOT = library.ROOT
V4_DIR = library.V4
#: 街区1 源文件（只读；重裁干净剖条用，不修改）。
STREET1_SOURCE = ROOT.parent / '巴黎建筑素材' / '巴黎民居街区1.schem'

#: create 模组壁柱 → vanilla 白色墙类（DECOMPOSE-street1：原版装配需人工替换白色墙类）。
#: diorite_wall 与 cut_calcite_wall 共享墙连接属性集，冻结连接态逐格保留。
VANILLA_WALL_SUBSTITUTE = 'minecraft:diorite_wall'
ALLOWED_WALL_SUBSTITUTIONS = {'create:cut_calcite_wall': VANILLA_WALL_SUBSTITUTE}


def load_piece(ident):
    """库件 schematic（ident 形如 'v4:st1-window-bay-noble'）。"""
    return library.load_detail(ident)


def piece_record(ident):
    """库件 record.json；ident 可带 'v4:' 前缀或裸名。"""
    name = ident.split(':', 1)[-1]
    return json.loads((V4_DIR / name / 'record.json').read_text(encoding='utf-8'))


def piece_source(ident):
    """assembly.json 用的来源摘要。"""
    record = piece_record(ident)
    return {'id': ident, 'source': record.get('source'),
            'source_bbox_xyz_half_open': record.get('source_bbox_xyz_half_open'),
            'clean_origin_source_xyz': record.get('clean_origin_source_xyz'),
            'compatible_vanilla': record.get('compatible_vanilla')}


def _palette_of(volume, states):
    palette = ['minecraft:air'] + sorted({s for s in states if not library._is_air_state(s)})
    ids = {value: index for index, value in enumerate(palette)}
    return palette, ids


def _state_grid(volume, palette):
    """Compare states, never palette indices (air may have any index)."""
    if volume.ndim != 3 or not volume.size or not np.issubdtype(volume.dtype, np.integer):
        raise ValueError('piece must be a nonempty integer volume')
    if int(volume.min()) < 0 or int(volume.max()) >= len(palette):
        raise ValueError('piece references an absent palette entry')
    return np.asarray(palette, dtype=object)[volume]


#: Digest cache keyed by (resolved path, size, mtime_ns). `_load_verified` re-hashes the
#: ORIGINAL source schematic for every one of the 44 derived pieces, and those sources are
#: large, so a dry run spent about 100 s hashing the same bytes dozens of times. Size plus
#: mtime is enough to know the file did not change, and any change invalidates the entry.
_DIGEST_CACHE = {}


def _digest(path):
    target = Path(path)
    stat = target.stat()
    key = (str(target.resolve()), stat.st_size, stat.st_mtime_ns)
    cached = _DIGEST_CACHE.get(key)
    if cached is not None:
        return cached
    value = hashlib.sha256(target.read_bytes()).hexdigest()
    _DIGEST_CACHE[key] = value
    return value


def validate_vanilla(path):
    """Strict target registry and independent round-trip, not namespace guessing."""
    result = subprocess.run([node_binary(), str(ROOT / 'tools/validate_schematic.cjs'), str(path)],
                            cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=120)
    try:
        report = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise ValueError('vanilla registry did not produce a report: ' + result.stderr[-1000:])
    if result.returncode != 0 or report.get('status') != 'PASS':
        raise ValueError('piece is not strict vanilla: ' + '; '.join(report.get('issues', [])))
    return report


def rotate_volume(volume, id_to_state, turns):
    """绕 Y 真旋转（位置 transform_point + 状态 transform_state），归一到最小角。

    返回 (volume, palette)：palette[0] 必为 air。turns=1 使朝北(-z)件转向东(+x)，
    与 architecture.Face.turns 约定一致（西=-x 面用 turns=3）。
    """
    turns %= 4
    air = {i for i, value in enumerate(id_to_state) if library._is_air_state(value)}
    height, depth, width = volume.shape
    cells = []
    for dy in range(height):
        for dz in range(depth):
            for dx in range(width):
                index = int(volume[dy, dz, dx])
                if index in air:
                    continue
                rx, ry, rz = transform_point(dx, dy, dz, turns)
                cells.append((rx, ry, rz, transform_state(str(id_to_state[index]), turns=turns)))
    if not cells:
        raise ValueError('rotate_volume: piece is all air')
    min_x = min(c[0] for c in cells)
    min_z = min(c[2] for c in cells)
    out_w = max(c[0] for c in cells) - min_x + 1
    out_d = max(c[2] for c in cells) - min_z + 1
    palette, ids = _palette_of(volume, [c[3] for c in cells])
    out = np.zeros((height, out_d, out_w), np.int32)
    for rx, ry, rz, value in cells:
        out[ry, rz - min_z, rx - min_x] = ids[value]
    return out, palette


def subcut_volume(volume, id_to_state, x0, x1, y0, y1, z0, z1):
    """半开区间子裁（局部坐标），随后裁掉外围全空气面。"""
    height, depth, width = volume.shape
    bounds = [x0, x1, y0, y1, z0, z1]
    if any(type(v) is not int for v in bounds) or not (
            0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height and 0 <= z0 < z1 <= depth):
        raise ValueError('subcut_volume: bounds outside piece')
    cut = volume[y0:y1, z0:z1, x0:x1]
    air = {i for i, value in enumerate(id_to_state) if library._is_air_state(value)}
    states = [str(id_to_state[int(i)]) for i in np.unique(cut) if int(i) not in air]
    palette, ids = _palette_of(cut, states)
    out = np.zeros(cut.shape, np.int32)
    for index in np.unique(cut):
        index = int(index)
        if index in air:
            continue
        out[cut == index] = ids[str(id_to_state[index])]
    return crop_air(out, palette)


def crop_air(volume, palette):
    """裁掉三个轴向上的外围全空气面（与库件清洗规范一致）。"""
    air_ids = [i for i, value in enumerate(palette) if library._is_air_state(value)]
    mask = ~np.isin(volume, air_ids)
    ys, zs, xs = np.where(mask)
    if not len(ys):
        raise ValueError('crop_air: piece is all air')
    return volume[ys.min():ys.max() + 1, zs.min():zs.max() + 1, xs.min():xs.max() + 1], palette


def patch_wall_states(volume, palette, target=VANILLA_WALL_SUBSTITUTE):
    """仅替换明确许可的 create:cut_calcite_wall，连接状态原样保留。

    返回 (out_volume, new_palette, replaced_cells)；替换后若与既有调色板状态撞名，
    合并索引并重映射 volume。
    """
    if target != VANILLA_WALL_SUBSTITUTE:
        raise ValueError('wall substitute is not explicitly allowed: ' + str(target))
    merged = []
    for value in palette:
        name, props = split_state(value)
        if name in ALLOWED_WALL_SUBSTITUTIONS:
            expected = {'east', 'north', 'south', 'west', 'up', 'waterlogged'}
            if set(props) != expected or any(props[d] not in ('none', 'low', 'tall')
                                             for d in ('east', 'north', 'south', 'west')) \
                    or any(props[d] not in ('true', 'false') for d in ('up', 'waterlogged')):
                raise ValueError('unsupported frozen wall properties: ' + value)
            merged.append(state(target, **props))
        else:
            merged.append(value)
    new_palette, lookup, remap = [], {}, {}
    for old_index, value in enumerate(merged):
        if value not in lookup:
            lookup[value] = len(new_palette)
            new_palette.append(value)
        remap[old_index] = lookup[value]
    out = np.zeros(volume.shape, np.int32)
    replaced = 0
    for old_index, value in enumerate(palette):
        mask = volume == old_index
        if not mask.any():
            continue
        if merged[old_index] != value:
            replaced += int(mask.sum())
        out[mask] = remap[old_index]
    return out, new_palette, replaced


def bay_positions(start, count, pattern=(4, 5, 5, 4), phase=0):
    """横向节奏：开间件宽 4（局部 x0/x3 为半墩），节距序列循环，phase 由种子决定。"""
    positions = [start]
    for i in range(count - 1):
        positions.append(positions[-1] + pattern[(phase + i) % len(pattern)])
    return positions


@dataclass
class Assembler:
    """一次组装的场景 + 放置账 + 派生件登记。

    ``dry_run`` walks the identical assembly path but writes no voxel: every stamp is
    still resolved, hash-verified against its frozen source and recorded, so the slot
    plan a caller gets back is the one the real build would produce. That is the point
    of doing it here rather than in a parallel re-implementation - a separate "planner"
    would drift from the builder, and the whole reason this project spent rounds chasing
    the wrong defect is that two descriptions of the same geometry disagreed.

    Collision accounting needs the scene to have contents, so it is reported as
    unmeasured in a dry run instead of being reported as zero.
    """
    scene: Scene
    derived_dir: Path = None
    dry_run: bool = False
    stamps: list = field(default_factory=list)
    derived: dict = field(default_factory=dict)
    _verified: dict = field(default_factory=dict, repr=False)
    _sources: dict = field(default_factory=dict, repr=False)

    def _load_verified(self, ident):
        """Bind each usable piece to its unchanged original source and transformation."""
        if ident in self.derived:
            row = self.derived[ident]
            path = ROOT / row['path']
            if _digest(path) != row['sha256']:
                raise ValueError('derived piece changed after registration: ' + ident)
            parent, evidence = self._load_verified(row['provenance']['source_id'])
            volume, palette = self._apply_operations(parent.volume, parent.id_to_state,
                                                      row['provenance']['operations'])
            read = load_schematic(path)
            if not np.array_equal(_state_grid(volume, palette),
                                  _state_grid(read.volume, read.id_to_state)):
                raise ValueError('derived piece does not reproduce from its source: ' + ident)
            if evidence != row['provenance']['source_evidence']:
                raise ValueError('derived source evidence changed: ' + ident)
            return read, {'id': ident, 'path': row['path'], 'sha256': row['sha256'],
                          'provenance': row['provenance']}
        if not ident.startswith('v4:'):
            raise ValueError('atlas assembly requires a source-backed v4 piece: ' + ident)
        record_path = V4_DIR / ident.split(':', 1)[1] / 'record.json'
        record = piece_record(ident)
        read = load_piece(ident)
        detail_hash = _digest(read.path)
        if detail_hash != record.get('schematic_sha256'):
            raise ValueError('library piece hash differs from its source record: ' + ident)
        source_path = (ROOT.parent / record['source']).resolve()
        source_hash = _digest(source_path)
        if source_hash != record.get('source_sha256'):
            raise ValueError('original source hash differs from library record: ' + ident)
        source_key = (str(source_path), source_hash)
        if source_key not in self._sources:
            self._sources[source_key] = load_schematic(source_path)
        source = self._sources[source_key]
        x, y, z = record['clean_origin_source_xyz']
        height, depth, width = read.volume.shape
        original = _state_grid(source.volume[y:y + height, z:z + depth, x:x + width],
                               source.id_to_state).copy()
        if original.shape != read.volume.shape:
            raise ValueError('library clean origin outside original source: ' + ident)
        for migration in record.get('cleaning', {}).get('version_migrations', []):
            mx, my, mz = migration['local_xyz']
            before, after = migration['before'], migration['after']
            if original[my, mz, mx] != before or split_state(before)[0] != 'minecraft:chain' \
                    or after != before.replace('minecraft:chain', 'minecraft:iron_chain', 1):
                raise ValueError('unapproved source state migration: ' + ident)
            original[my, mz, mx] = after
        if not np.array_equal(original, _state_grid(read.volume, read.id_to_state)):
            raise ValueError('library piece differs from original frozen source: ' + ident)
        evidence = {'id': ident, 'path': str(read.path.resolve().relative_to(ROOT)),
                    'sha256': detail_hash, 'record_sha256': _digest(record_path),
                    'original_source': record['source'], 'original_source_sha256': source_hash,
                    'clean_origin_source_xyz': record['clean_origin_source_xyz'],
                    'source_bbox_xyz_half_open': record.get('source_bbox_xyz_half_open'),
                    'source_states_equal': True,
                    'version_migrations': record.get('cleaning', {}).get('version_migrations', [])}
        return read, evidence

    @staticmethod
    def _apply_operations(volume, palette, operations):
        volume, palette = volume.copy(), list(palette)
        for operation in operations:
            kind = operation.get('op')
            if kind == 'rotate':
                turns = operation.get('turns')
                if type(turns) is not int or not 0 <= turns <= 3:
                    raise ValueError('rotate requires turns in 0..3')
                volume, palette = rotate_volume(volume, palette, turns)
            elif kind == 'subcut':
                x0, y0, z0, x1, y1, z1 = operation['bbox']
                volume, palette = subcut_volume(volume, palette, x0, x1, y0, y1, z0, z1)
            elif kind == 'patch_wall_states':
                volume, palette, _ = patch_wall_states(
                    volume, palette, operation.get('target', VANILLA_WALL_SUBSTITUTE))
            else:
                raise ValueError('unapproved derived operation: ' + str(kind))
        return volume, palette

    def register_derived(self, derived_id, volume, palette, note, *, source_id=None, operations=None):
        """派生件逐格复现原件操作后落盘；禁止凭自身输出证明来源。"""
        if not source_id or not isinstance(operations, list):
            raise ValueError('derived piece requires source_id and explicit operations')
        if not re.fullmatch(r'[A-Za-z0-9_.:@-]+', derived_id) or derived_id in self.derived:
            raise ValueError('invalid or duplicate derived id: ' + str(derived_id))
        operations = json.loads(json.dumps(operations))
        source, evidence = self._load_verified(source_id)
        expected_volume, expected_palette = self._apply_operations(
            source.volume, source.id_to_state, operations)
        if not np.array_equal(_state_grid(volume, palette),
                              _state_grid(expected_volume, expected_palette)):
            raise ValueError('derived output differs from declared source operations: ' + derived_id)
        if self.derived_dir is None:
            raise ValueError('derived_dir is required to register a derived piece')
        folder = Path(self.derived_dir)
        if not folder.is_absolute():
            folder = ROOT / folder
        path = folder / (derived_id.replace(':', '_').replace('@', '__') + '.schem')
        rel = str(path.resolve().relative_to(ROOT))
        if any(row['path'] == rel for row in self.derived.values()):
            raise ValueError('derived id filename collision: ' + derived_id)
        # Reuse an already-registered derived file when it reproduces from the same source
        # and operations. Registering writes a .schem and then shells out to node for the
        # vanilla-registry check, once per derived piece; with 44 pieces that dominated the
        # dry run (117 s), which defeats the purpose of a cheap spec loop. The bytes are
        # re-derived and compared above, so reuse cannot mask a changed source.
        if path.is_file():
            read_back = load_schematic(path)
            if np.array_equal(_state_grid(volume, palette),
                              _state_grid(read_back.volume, read_back.id_to_state)):
                existing = next((row for row in self.derived.values() if row['path'] == rel), None)
                if existing is None:
                    info = {'sha256': _digest(path)}
                    registry = ({'status': 'REUSED_UNCHANGED', 'note': 'derived file reproduces '
                                 'from its source; registry check deferred to the real build'}
                                if self.dry_run else validate_vanilla(path))
                    self.derived[derived_id] = {
                        'path': rel, 'note': note, 'sha256': info['sha256'],
                        'nonair_cells': int(sum(np.count_nonzero(volume == i)
                                                for i, value in enumerate(palette)
                                                if not library._is_air_state(value))),
                        'provenance': {'status': 'PASS', 'source_id': source_id,
                                       'operations': operations, 'source_evidence': evidence,
                                       'output_states_equal': True,
                                       'door_policy': 'PRESERVE_SOURCE_HALF_STATES',
                                       'game_acceptance': 'NOT_RUN'},
                        'registry': registry, 'compatible_vanilla': True,
                        'size_whd': [int(volume.shape[2]), int(volume.shape[0]),
                                     int(volume.shape[1])], 'reused': True}
                    return rel
        info = write_schematic(path, volume, palette, name='ATLAS derived: ' + derived_id)
        registry = ({'status': 'DEFERRED_DRY_RUN',
                     'note': 'vanilla-registry check runs on the real build'}
                    if self.dry_run else validate_vanilla(path))
        self.derived[derived_id] = {
            'path': rel, 'note': note, 'sha256': info['sha256'],
            'nonair_cells': int(sum(np.count_nonzero(volume == i) for i, value in enumerate(palette)
                                   if not library._is_air_state(value))),
            'provenance': {'status': 'PASS', 'source_id': source_id, 'operations': operations,
                           'source_evidence': evidence, 'output_states_equal': True,
                           'door_policy': 'PRESERVE_SOURCE_HALF_STATES',
                           'game_acceptance': 'NOT_RUN'},
            'registry': registry, 'compatible_vanilla': True,
            'size_whd': [int(volume.shape[2]), int(volume.shape[0]), int(volume.shape[1])]}
        self._verified[(derived_id, info['sha256'])] = registry
        return rel

    def stamp(self, ident, x, y, z, role, clip=None, volume=None, palette=None, *, allow_scene_clip=False):
        """落位一件（ident 可为库件 id 或已登记派生件 id；锚点=件包围盒最小角）。

        clip=(x0, z0, x1, z1) 闭区间：出界格跳过并计数（共墙线裁齐用）。
        """
        read, evidence = self._load_verified(ident)
        if volume is not None and not np.array_equal(_state_grid(volume, palette),
                                                     _state_grid(read.volume, read.id_to_state)):
            raise ValueError('stamp override differs from registered piece: ' + ident)
        volume, palette = read.volume, read.id_to_state
        air = {i for i, value in enumerate(palette) if library._is_air_state(value)}
        key = (ident, _digest(read.path))
        if key not in self._verified:
            self._verified[key] = validate_vanilla(read.path)
        if clip is not None and (len(clip) != 4 or any(type(v) is not int for v in clip)
                                 or clip[0] > clip[2] or clip[1] > clip[3]):
            raise ValueError('clip requires ordered integer x0,z0,x1,z1 inclusive')
        height, depth, width = volume.shape
        placed = clipped = scene_clipped = 0
        same_state_overlap = overwritten = 0
        overwrite_owners, samples = {}, []
        owner = 'library:%s#%d' % (ident, len(self.stamps))
        for dy in range(height):
            for dz in range(depth):
                for dx in range(width):
                    index = int(volume[dy, dz, dx])
                    if index in air:
                        continue
                    sx, sy, sz = x + dx, y + dy, z + dz
                    if clip and not (clip[0] <= sx <= clip[2] and clip[1] <= sz <= clip[3]):
                        clipped += 1
                        continue
                    if not (0 <= sy < self.scene.volume.shape[0]
                            and 0 <= sz < self.scene.volume.shape[1]
                            and 0 <= sx < self.scene.volume.shape[2]):
                        clipped += 1
                        scene_clipped += 1
                        continue
                    old = self.scene.palette[int(self.scene.volume[sy, sz, sx])]
                    requested = str(palette[index])
                    if not self.dry_run and not library._is_air_state(old):
                        if old == requested:
                            same_state_overlap += 1
                        else:
                            overwritten += 1
                            previous = self.scene.owner.get((sx, sy, sz), 'structure')
                            overwrite_owners[previous] = overwrite_owners.get(previous, 0) + 1
                            if len(samples) < 10:
                                samples.append({'xyz': [sx, sy, sz], 'before': old,
                                                'after': requested, 'previous_owner': previous})
                    if not self.dry_run:
                        self.scene.put(sx, sy, sz, requested, owner)
                    placed += 1
        record = {'id': ident, 'role': role, 'anchor': [int(x), int(y), int(z)],
                  'turns': 0, 'placed': placed, 'clipped': clipped,
                  'size_whd': [width, height, depth], 'clip': list(clip) if clip is not None else None,
                  'scene_clipped': scene_clipped, 'allow_scene_clip': bool(allow_scene_clip),
                  'owner': owner, 'source_evidence': evidence,
                  'collisions': {'measured': not self.dry_run,
                                 'same_state_overlap': same_state_overlap,
                                 'different_state_overwrites': overwritten,
                                 'previous_owners': overwrite_owners, 'samples': samples}}
        self.stamps.append(record)
        return record

    def audit_rows(self):
        used_sources = {stamp['id']: stamp['source_evidence'] for stamp in self.stamps
                        if stamp['id'] not in self.derived}
        rows = [dict(row, source_evidence=used_sources[row['id']])
                if row['id'] in used_sources else row for row in library.catalogue()['entries']]
        return rows + [dict(row, id=ident) for ident, row in self.derived.items()]

    def audit_entries(self):
        return [{'id': row['id'], 'x': row['anchor'][0], 'y': row['anchor'][1],
                 'z': row['anchor'][2], 'turns': row['turns'], 'role': row['role'],
                 'clip': row['clip'], 'allow_scene_clip': row['allow_scene_clip']} for row in self.stamps]
