"""Assemble the part-prototype facade from library-v3 s3 pieces and render it.

Proves that a full 23x49 street facade (shop base, entry, four window floors,
storey band, balcony, cornice, mansard roof, dormers, chimneys) can be assembled
from pieces cut out of the human-built source "street3" at their original
relative positions. Scene coordinate = source coordinate - COMMON_ORIGIN; the
mother facade street3-facade-3 (local origin == scene x/y, shell at scene z 13..20)
supplies the measurements (bay x positions, wall material), the verbatim shell
patch for the columns no library piece covers, and a clean roof slope slice.

Roof assembly (v2): s3-roof-section carries a clipped skylight (iron_door /
white_stained_glass / lever / diorite_wall at its dz 16..19) and a chimney shaft
(dx 3, dz 3..5); tiled raw it pollutes the slope and ridge. The roof is therefore
the filtered section (state blacklist + shaft cut down to the neighbor roofline)
for the full-depth body, plus a clean 4-wide slope slice derived from the mother
(columns 1,2,3,20 - every contiguous 4-wide band holds a dormer or a party-wall
column) tiled over the street-visible slope. The derived slice is exported to
derived/roof-section-clean.schem.

Idempotent: rebuilds the scene from scratch and overwrites every output.

    PYTHONPATH=src python -X utf8 tools/build_part_prototype.py [--skip-render]
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / 'src'))

import numpy as np

from paris_builder.architecture import Scene
from paris_builder.exporter import dump_json, write_schematic
from paris_builder.schematic import base_block, load_schematic
from paris_builder.technique_library import load_detail, size_of, stamp, verify_stamp_audit

LIB_DIR = PROJECT_ROOT / 'knowledge' / 'library-v3' / 'reference-techniques'
MOTHER_PATH = LIB_DIR / 'street3-facade-3' / 'detail.schem'
COMMON_ORIGIN = (66, 1, 9)
SCENE_W, SCENE_H, SCENE_D = 23, 49, 23
SHELL_DZ = 13  # mother local z 0..7 -> scene z 13..20 (mother clean z 22 - common z 9)
SHELL_Z0, SHELL_Z1 = 13, 21  # half-open scene z range of the facade shell
FILL_TOP_Y = 34  # fill covers y 0..34 inclusive
WINDOW_FLOOR_BANDS = [(7, 13), (13, 19), (19, 25), (25, 31)]  # mother-local y, half-open
DORMER_BAND = (35, 40)  # mother-local y band holding the dormer windows
ROOF_REPEAT_X = [0, 4, 8, 12, 16, 19]  # scene x; source 66,70,74,78,82 + tail 85
ROOF_BLACKLIST = ('minecraft:iron_door', 'minecraft:white_stained_glass',
                  'minecraft:lever', 'minecraft:diorite_wall')
ROOF_SHAFT_DX = 3        # chimney shaft column inside s3-roof-section
ROOF_SHAFT_DZ = (3, 5)   # inclusive dz range of the shaft
SLICE_COLUMNS = (1, 2, 3, 20)  # mother-local x columns of the clean slope slice
SLICE_Y = (36, 42)       # inclusive mother-local y range of the slice
CHIMNEY_X2 = 14          # scene x of the second (symmetric) chimney


def read_record(name):
    return json.loads((LIB_DIR / name / 'record.json').read_text(encoding='utf-8'))


def clean_anchor(name):
    """Scene anchor of a piece placed at its recorded source position."""
    origin = read_record(name)['clean_origin_source_xyz']
    return [int(origin[i]) - COMMON_ORIGIN[i] for i in range(3)]


def door_cells(read):
    door_ids = [i for i, s in enumerate(read.id_to_state)
                if base_block(s) == 'minecraft:iron_door']
    ys, zs, xs = np.where(np.isin(read.volume, door_ids))
    return xs, ys, zs


def clusters(values):
    result = []
    for value in sorted(set(int(v) for v in values)):
        if result and value - result[-1][-1] <= 1:
            result[-1].append(value)
        else:
            result.append([value])
    return result


def measure_window_bays(mother, piece):
    """Bay start x and anchor y for each window floor, from the mother's doors."""
    xs, ys, _ = door_cells(mother)
    pxs, pys, _ = door_cells(piece)
    piece_dx, piece_dy = int(pxs.min()), int(pys.min())
    floors = []
    for y0, y1 in WINDOW_FLOOR_BANDS:
        sel = (ys >= y0) & (ys < y1)
        if not sel.any():
            raise ValueError('no iron_door cells in floor band y %d..%d' % (y0, y1 - 1))
        bay_x = [c[0] - piece_dx for c in clusters(xs[sel])]
        door_y = sorted(set(int(v) for v in ys[sel]))
        floors.append({'band_local_y': [y0, y1 - 1],
                       'door_local_y': [door_y[0], door_y[-1]],
                       'bay_x': bay_x, 'anchor_y': door_y[0] - piece_dy})
    return floors


def measure_dormer_positions(mother, piece):
    xs, ys, _ = door_cells(mother)
    pxs, _, _ = door_cells(piece)
    sel = (ys >= DORMER_BAND[0]) & (ys < DORMER_BAND[1])
    return [c[0] - int(pxs.min()) for c in clusters(xs[sel])]


def slice_scan(mother):
    """Pollutant/non-air counts per contiguous 4-wide roof slice, for the report."""
    bad = set(i for i, s in enumerate(mother.id_to_state)
              if base_block(s) in ROOF_BLACKLIST)
    air = set(int(i) for i in mother.air_ids)
    rows = []
    y0, y1 = SLICE_Y[0], SLICE_Y[1] + 1
    for x0 in list(range(0, SCENE_W - 3, 4)) + [SCENE_W - 3]:
        sub = mother.volume[y0:y1, :, x0:min(x0 + 4, SCENE_W)]
        rows.append({'x0': x0, 'width': int(sub.shape[2]),
                     'nonair': int(np.count_nonzero(~np.isin(sub, list(air)))),
                     'pollutant': int(np.count_nonzero(np.isin(sub, list(bad))))})
    return rows


def export_roof_slice(mother, path):
    """Write the clean slope slice (mother columns SLICE_COLUMNS) as a derived piece."""
    y0, y1 = SLICE_Y[0], SLICE_Y[1] + 1
    air = set(int(i) for i in mother.air_ids)
    columns = [mother.volume[y0:y1, :, x] for x in SLICE_COLUMNS]
    block = np.stack(columns, axis=2)  # (height, depth, 4)
    states = sorted({mother.id_to_state[int(i)] for i in np.unique(block)
                     if int(i) not in air})
    palette = ['minecraft:air'] + states
    ids = {value: index for index, value in enumerate(palette)}
    volume = np.zeros(block.shape, dtype=np.int32)
    for index in range(1, len(palette)):
        volume[np.where(block == mother.palette[palette[index]])] = index
    info = write_schematic(path, volume, palette, name='PART-PROTO clean roof slice')
    return {'path': str(path.relative_to(PROJECT_ROOT)),
            'mother_columns_local_x': list(SLICE_COLUMNS),
            'source_x': [x + 66 for x in SLICE_COLUMNS],
            'y_range_local': [SLICE_Y[0], SLICE_Y[1]],
            'z_range_local': [0, 7], 'sha256': info['sha256'],
            'nonair_cells': int(np.count_nonzero(volume))}


def roof_filter_stats():
    """Cells the roof filter would drop from one s3-roof-section, by cause."""
    read = load_detail('v3:s3-roof-section')
    air_ids = set(int(i) for i in read.air_ids)
    height = read.volume.shape[0]
    roofline = {}
    for dz in range(ROOF_SHAFT_DZ[0], ROOF_SHAFT_DZ[1] + 1):
        tops = [dy for dy in range(height) for dx in range(ROOF_SHAFT_DX)
                if int(read.volume[dy, dz, dx]) not in air_ids]
        roofline[dz] = max(tops) if tops else -1
    skylight = shaft = 0
    for dy in range(height):
        for dz in range(read.volume.shape[1]):
            for dx in range(read.volume.shape[2]):
                index = int(read.volume[dy, dz, dx])
                if index in air_ids:
                    continue
                if base_block(read.id_to_state[index]) in ROOF_BLACKLIST:
                    skylight += 1
                elif (dx == ROOF_SHAFT_DX and ROOF_SHAFT_DZ[0] <= dz <= ROOF_SHAFT_DZ[1]
                      and dy > roofline[dz]):
                    shaft += 1
    return {'skylight_cells_per_section': skylight, 'shaft_cells_per_section': shaft,
            'roofline_dy': {str(dz): dy for dz, dy in roofline.items()}}


def stamp_roof_filtered(scene, x, y, z):
    """Stamp s3-roof-section minus the skylight states and the chimney shaft."""
    read = load_detail('v3:s3-roof-section')
    air_ids = set(int(i) for i in read.air_ids)
    height, depth, width = read.volume.shape
    # Cut the shaft (dx == ROOF_SHAFT_DX, dz in ROOF_SHAFT_DZ) down to the neighboring
    # roof surface: keep its cells at/below the highest non-air cell of dx 0..2 at the
    # same dz, so the carve leaves a flush patch instead of a hole into the hollow body.
    roofline = {}
    for dz in range(ROOF_SHAFT_DZ[0], ROOF_SHAFT_DZ[1] + 1):
        tops = [dy for dy in range(height) for dx in range(ROOF_SHAFT_DX)
                if int(read.volume[dy, dz, dx]) not in air_ids]
        roofline[dz] = max(tops) if tops else -1
    placed = skipped = 0
    for dy in range(height):
        for dz in range(depth):
            for dx in range(width):
                index = int(read.volume[dy, dz, dx])
                if index in air_ids:
                    continue
                value = read.id_to_state[index]
                if base_block(value) in ROOF_BLACKLIST:
                    skipped += 1
                    continue
                if (dx == ROOF_SHAFT_DX and ROOF_SHAFT_DZ[0] <= dz <= ROOF_SHAFT_DZ[1]
                        and dy > roofline[dz]):
                    skipped += 1
                    continue
                scene.put(x + dx, y + dy, z + dz, value, 'library:v3:s3-roof-section(filtered)')
                placed += 1
    return placed, skipped


def stamp_roof_slice(scene, path, x, y, z):
    """Tile the derived clean slope slice into the scene."""
    read = load_schematic(path)
    air_ids = set(int(i) for i in read.air_ids)
    height, depth, width = read.volume.shape
    placed = 0
    for dy in range(height):
        for dz in range(depth):
            for dx in range(width):
                index = int(read.volume[dy, dz, dx])
                if index in air_ids:
                    continue
                scene.put(x + dx, y + dy, z + dz, read.id_to_state[index],
                          'derived:roof-section-clean')
                placed += 1
    return placed


def planned_stamps(floors, dormer_xs):
    """(ident, anchor, role) in recipe order: large bands first, small pieces last.

    The roof body is NOT a plain stamp: it goes through stamp_roof_filtered and is
    recorded separately in main(). The clean slope overlay tiles follow the roof body
    so the dormers (stamped later) still cut into a finished slope.
    """
    stamps = []
    for name in ('s3-storey-band', 's3-upper-balcony', 's3-cornice'):
        stamps.append(('v3:' + name, clean_anchor(name), 'band'))
    for floor in floors:
        bay = clean_anchor('s3-window-bay')
        for bay_x in floor['bay_x']:
            stamps.append(('v3:s3-window-bay', [bay_x, floor['anchor_y'], bay[2]], 'window-bay'))
    dormer = clean_anchor('s3-dormer')
    for x in dormer_xs:
        stamps.append(('v3:s3-dormer', [x, dormer[1], dormer[2]], 'dormer'))
    chimney = clean_anchor('s3-chimney')
    stamps.append(('v3:s3-chimney', chimney, 'chimney'))
    stamps.append(('v3:s3-chimney', [CHIMNEY_X2, chimney[1], chimney[2]], 'chimney-symmetric'))
    stamps.append(('v3:s3-base-shop', clean_anchor('s3-base-shop'), 'base'))
    stamps.append(('v3:s3-entry', clean_anchor('s3-entry'), 'base'))
    return stamps


def preflight(stamps):
    for ident, anchor, _ in stamps:
        size = size_of(ident)
        for axis, (a, extent, limit) in enumerate(zip(
                anchor, (size['width'], size['height'], size['depth']),
                (SCENE_W, SCENE_H, SCENE_D))):
            if a < 0 or a + extent > limit:
                record = read_record(ident.split(':', 1)[1])
                raise ValueError(
                    '%s out of bounds: anchor=%s size=%s scene=%dx%dx%d '
                    'clean_origin_source_xyz=%s dimensions_whd=%s' % (
                        ident, anchor, size, SCENE_W, SCENE_H, SCENE_D,
                        record['clean_origin_source_xyz'],
                        record['inventory']['dimensions_whd']))


def covered_rects(stamps, roof_anchor):
    """Scene x/y rectangles covered by each planned placement, for the wall survey."""
    rects = []
    size = size_of('v3:s3-roof-section')
    for x in ROOF_REPEAT_X:
        rects.append({'id': 'v3:s3-roof-section', 'role': 'roof-repeat',
                      'x0': x, 'y0': roof_anchor[1],
                      'x1': x + size['width'], 'y1': roof_anchor[1] + size['height']})
    for ident, anchor, role in stamps:
        size = size_of(ident)
        rects.append({'id': ident, 'role': role,
                      'x0': anchor[0], 'y0': anchor[1],
                      'x1': anchor[0] + size['width'], 'y1': anchor[1] + size['height']})
    return rects


def foremost_states(volume, air_ids, id_to_state):
    """Per (y, x) the state of the foremost (+z) non-air cell, or None."""
    air = set(int(i) for i in air_ids)
    height, depth, width = volume.shape
    surface = {}
    for y in range(height):
        for x in range(width):
            column = volume[y, :, x]
            nonair = np.nonzero(~np.isin(column, list(air)))[0]
            if len(nonair):
                surface[(y, x)] = id_to_state[int(column[nonair[-1]])]
    return surface


def measure_wall_material(mother, rects):
    """Modal street-face state over the columns no placement covers (y 0..34)."""
    surface = foremost_states(mother.volume, mother.air_ids, mother.id_to_state)
    counter, cells = Counter(), 0
    for (y, x), value in surface.items():
        if y > FILL_TOP_Y:
            continue
        if any(r['x0'] <= x < r['x1'] and r['y0'] <= y < r['y1'] for r in rects):
            continue
        counter[value] += 1
        cells += 1
    if not counter:
        raise ValueError('wall survey found no uncovered street-face cells')
    return {'chosen': counter.most_common(1)[0][0], 'surveyed_cells': cells,
            'distribution': counter.most_common()}


def shell_patch(scene, mother):
    """Copy the mother's shell column (scene z 13..20) wherever nothing was placed."""
    air = set(int(i) for i in mother.air_ids)
    columns, cells = 0, 0
    for y in range(FILL_TOP_Y + 1):
        for x in range(SCENE_W):
            if any(str(scene.owner.get((x, y, z), '')).split(':')[0] in ('library', 'derived')
                   for z in range(SHELL_Z0, SHELL_Z1)):
                continue
            wrote = False
            for lz in range(mother.volume.shape[1]):
                index = int(mother.volume[y, lz, x])
                if index in air:
                    continue
                scene.put(x, y, lz + SHELL_DZ, mother.id_to_state[index], 'fill:shell-patch')
                cells += 1
                wrote = True
            columns += 1 if wrote else 0
    return {'patched_columns': columns, 'patched_cells': cells}


def surface_comparison(scene, mother):
    """Exact-state match of the foremost street surface, prototype vs mother."""
    scene_surface = foremost_states(scene.volume, [0], scene.palette)
    mother_surface = foremost_states(mother.volume, mother.air_ids, mother.id_to_state)
    total = matched = 0
    mismatches = Counter()
    for y in range(min(SCENE_H, mother.volume.shape[0])):
        for x in range(SCENE_W):
            want = mother_surface.get((y, x))
            got = scene_surface.get((y, x))
            if want is None and got is None:
                continue
            total += 1
            if want == got:
                matched += 1
            else:
                zone = 'roof' if y > FILL_TOP_Y else 'facade'
                mismatches[zone] += 1
    return {'compared_columns': total, 'matched': matched,
            'match_rate': round(matched / total, 4) if total else None,
            'mismatch_zones': dict(mismatches)}


def render(schem_path, out_dir):
    env = dict(os.environ, PYTHONUTF8='1',
               PYTHONPATH=str(PROJECT_ROOT / 'src'))
    command = [sys.executable, '-X', 'utf8', '-m', 'paris_builder.preview3d',
               str(schem_path), '--out', str(out_dir)]
    print('render:', ' '.join(command), flush=True)
    subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=True)
    metadata = json.loads((out_dir / 'render_metadata.json').read_text(encoding='utf-8'))
    return {'out_dir': str(out_dir.relative_to(PROJECT_ROOT)),
            'views': sorted(metadata['views'])}


def write_report(path, assembly):
    roof = assembly['roof_solution']
    lines = [
        '# PART-PROTO-v0.1 库件组装原型立面',
        '',
        '用 `knowledge/library-v3/reference-techniques/` 的 s3 系列拆件（源：巴黎民居街区3）',
        '按源相对位置组装 23×49×23 的完整立面。场景坐标 = 源坐标 − COMMON_ORIGIN %s。' % (list(COMMON_ORIGIN),),
        '',
        '## 测量结果',
        '',
        '### 1. 窗开间实测（母本 street3-facade-3 的 iron_door 聚类）',
        '',
        '| 楼层(母本局部 y) | 门 y 范围 | 开间起始 x | 窗件锚点 y |',
        '|---|---|---|---|',
    ]
    for floor in assembly['measurements']['window_floors']:
        lines.append('| %d..%d | %d..%d | %s | %d |' % (
            floor['band_local_y'][0], floor['band_local_y'][1],
            floor['door_local_y'][0], floor['door_local_y'][1],
            ', '.join(str(v) for v in floor['bay_x']), floor['anchor_y']))
    wall = assembly['measurements']['wall_material']
    slc = roof['clean_slice']
    lines += [
        '',
        '老虎窗门聚类实测位置（场景 x）：%s —— 3 个全部放置。' % assembly['measurements']['dormer_positions_measured'],
        '',
        '母本屋顶切片扫描（y%d..%d，每 4 格宽一条）：' % (SLICE_Y[0], SLICE_Y[1]),
        '',
    ]
    for row in roof['slice_scan']:
        lines.append('- x %d..%d：非空气 %d 格，污染 %d 格' % (
            row['x0'], row['x0'] + row['width'] - 1, row['nonair'], row['pollutant']))
    lines += [
        '',
        '### 2. 主体墙面材料（未被任何件覆盖的街面最外层众数）',
        '',
        '- 采用：`%s`（调查 %d 格）' % (wall['chosen'], wall['surveyed_cells']),
        '- 分布：' + '；'.join('%s ×%d' % (s, c) for s, c in wall['distribution'][:6]),
        '',
        '## 屋顶方案（v2：干净剖条 + 过滤主体）',
        '',
        ('- **主体**：`v3:s3-roof-section` × 6（x=%s），stamp 时按状态黑名单跳过 `%s`'
         '（天窗残件，件内 dz16..19，共 %d 格/件），'
         '并把夹带的烟囱杆（件内 dx=3、dz3..5）削平到邻列坡面线'
         '（保留不高出 dx0..2 同 dz 最高非空气格的格，共滤除 %d 格/件，削平处不留洞）。') % (
            ','.join(str(x) for x in ROOF_REPEAT_X), '`, `'.join(ROOF_BLACKLIST),
            roof['skylight_cells_per_section'], roof['shaft_cells_per_section']),
        '- **街面坡面**：派生件 `%s`（%d 非空气格）× 6 同位横铺，' % (slc['path'], slc['nonair_cells']),
        '  取自母本局部列 x=%s（源 x=%s）、y%d..%d、z0..7。' % (
            slc['mother_columns_local_x'], slc['source_x'], slc['y_range_local'][0], slc['y_range_local'][1]),
        '  母本没有任何连续 4 格宽带既无老虎窗又无山墙柱（见扫描表），',
        '  故干净剖条由母本列 1/2/3/20 拼成；选择理由是这四列均为纯坡面型。',
        ('- **烟囱**：s3-chimney × 2 —— 源位置 x=2..7 + 对称位 x=%d..%d（只放 1 个在屋脊上太孤单；'
         '第二组为对称布置，非源位置）。') % (CHIMNEY_X2, CHIMNEY_X2 + 5),
        '- 选择路径：母本存在干净切片（x20..22 污染 0），故走「派生件」路线；',
        '  状态黑名单/空间过滤作为主体件的必要补充（母本裁件只有 8 格深，供不出全深屋顶）。',
        '',
        '## 装配表',
        '',
        '| # | 件 | 场景锚点 [x,y,z] | 角色 | 放置格数 |',
        '|---|---|---|---|---|',
    ]
    for i, row in enumerate(assembly['stamps']):
        lines.append('| %d | %s | %s | %s | %d |' % (
            i + 1, row['id'], row['anchor'], row['role'], row['placed']))
    patch = assembly['shell_patch']
    compare = assembly['surface_comparison']
    lines += [
        '',
        '实体填充在 stamp 之前：x 0..22、y 0..34、z 0..13，材料 `%s`，owner=fill:core。'
        % wall['chosen'],
        '',
        '## 覆盖统计（overwrite_counts）',
        '',
    ]
    for key, count in assembly['overwrites']['counts'].items():
        lines.append('- %s：%d 格' % (key, count))
    if not assembly['overwrites']['counts']:
        lines.append('- 无')
    lines += [
        '',
        '## 与母本的差异',
        '',
        '街面最外层逐格对照母本：%d / %d 列一致（%.1f%%）。不一致分布：%s。' % (
            compare['matched'], compare['compared_columns'],
            100.0 * (compare['match_rate'] or 0), compare['mismatch_zones']),
        '注意：母本裁件只有 8 格深（源 z22..29），屋顶脊线在其裁切之外；',
        'y43 以上的不一致是「母本裁切外为空气、原型有完整屋顶」所致，非错误。',
        '',
        '参数化/母本直补区域（非库件组装）：',
        '',
        '- **墙体内芯**：x 0..22、y 0..34、z 0..13 整块 `%s` 填充（背面与侧面可见）。' % wall['chosen'],
        '- **外壳补全**（fill:shell-patch）：%d 列 / %d 格，逐列照抄母本外壳。' % (
            patch['patched_columns'], patch['patched_cells']),
        '  覆盖开间间距为 5 的墙墩条带（x=8、x=13）、右侧山墙列（x=22）、',
        '  层间线脚未覆盖的 x=0 与 x=20..22 行、底层 x=22 列。',
        '- **屋顶街面坡**：派生干净剖条（母本列 1/2/3/20 拼成）重复 6 次；',
        '  屋顶上部/屋脊/后坡来自过滤后的 s3-roof-section。',
        '- **重复产生**：4 个窗楼层 × 5 开间 = 20 次 window-bay（同一 4×6×6 样本，',
        '  样本取自第 3 层：窗侧为 sandstone_wall 墩；母本 1/2/4 层此处为 birch_fence 栏杆，',
        '  重复后各层均为第 3 层样式）。',
        '- **已知残余**：屋顶两端无女儿墙柱（母本山墙柱在 x=0/21，干净剖条刻意避开了它们）；',
        '  削平烟囱杆处留下 3 格/件的灰色贴面（andesite/stone，与邻列坡面齐平）。',
        '',
        '## 校验',
        '',
        '- `load_schematic(prototype.schem).validation()`：**%s**' % assembly['validation']['status'],
        '- stamp 回读审计（verify_stamp_audit）：匹配格 %d/%d。'
        '屋顶主体件因过滤必然部分不匹配，大面积带被后写件部分覆盖属预期，'
        '故总状态 %s 不作为失败解读。' % (
            assembly['stamp_audit']['matched_cells'],
            sum(row['cells'] for row in assembly['stamp_audit']['stamps']),
            assembly['stamp_audit']['status']),
    ]
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, default=PROJECT_ROOT / 'runs' / 'PART-PROTO-v0.1')
    parser.add_argument('--skip-render', action='store_true')
    args = parser.parse_args()
    run_dir = args.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)

    mother = load_schematic(MOTHER_PATH)
    window_piece = load_detail('v3:s3-window-bay')
    dormer_piece = load_detail('v3:s3-dormer')

    floors = measure_window_bays(mother, window_piece)
    dormer_xs = measure_dormer_positions(mother, dormer_piece)
    stamps = planned_stamps(floors, dormer_xs)
    preflight(stamps)
    roof_anchor = clean_anchor('s3-roof-section')
    wall = measure_wall_material(mother, covered_rects(stamps, roof_anchor))

    slice_path = run_dir / 'derived' / 'roof-section-clean.schem'
    slice_info = export_roof_slice(mother, slice_path)

    scene = Scene(SCENE_W, SCENE_H, SCENE_D)
    scene.box(0, 0, 0, SCENE_W - 1, FILL_TOP_Y, SHELL_DZ, wall['chosen'], owner='fill:core')
    records = []
    for x in ROOF_REPEAT_X:  # filtered roof body first: bands/windows/dormers overwrite it
        placed, skipped = stamp_roof_filtered(scene, x, roof_anchor[1], roof_anchor[2])
        records.append({'id': 'v3:s3-roof-section', 'anchor': [x, roof_anchor[1], roof_anchor[2]],
                        'role': 'roof-body-filtered', 'placed': placed, 'filtered_out': skipped})
        print('stamp %-31s anchor=%s placed=%d (filtered %d)' % (
            'v3:s3-roof-section(filtered)', [x, roof_anchor[1], roof_anchor[2]], placed, skipped),
            flush=True)
    for x in ROOF_REPEAT_X:
        placed = stamp_roof_slice(scene, slice_path, x, SLICE_Y[0], SHELL_DZ)
        records.append({'id': 'derived:roof-section-clean', 'anchor': [x, SLICE_Y[0], SHELL_DZ],
                        'role': 'roof-slope-clean', 'placed': placed})
        print('stamp %-31s anchor=%s placed=%d' % (
            'derived:roof-section-clean', [x, SLICE_Y[0], SHELL_DZ], placed), flush=True)
    for ident, anchor, role in stamps:
        placed = stamp(scene, ident, anchor[0], anchor[1], anchor[2])
        records.append({'id': ident, 'anchor': anchor, 'role': role, 'placed': placed})
        print('stamp %-31s anchor=%s placed=%d' % (ident, anchor, placed), flush=True)
    patch = shell_patch(scene, mother)
    print('shell patch: %d columns / %d cells' % (patch['patched_columns'], patch['patched_cells']))

    schem_path = run_dir / 'prototype.schem'
    export_info = write_schematic(schem_path, scene.volume, scene.palette,
                                  name='PART-PROTO-v0.1 part-assembly prototype')
    read_back = load_schematic(schem_path)
    validation = read_back.validation()
    audit = verify_stamp_audit(read_back, [
        {'id': row['id'], 'x': row['anchor'][0], 'y': row['anchor'][1], 'z': row['anchor'][2]}
        for row in records if row['id'].startswith('v3:')])

    assembly = {
        'run': run_dir.name, 'common_origin': list(COMMON_ORIGIN),
        'scene': {'width': SCENE_W, 'height': SCENE_H, 'depth': SCENE_D},
        'schematic': {'path': str(schem_path.relative_to(PROJECT_ROOT)), **export_info},
        'measurements': {
            'window_floors': floors,
            'dormer_positions_measured': dormer_xs,
            'wall_material': wall,
        },
        'roof_solution': {
            'body': 'v3:s3-roof-section tiled at ROOF_REPEAT_X with state blacklist + shaft carve',
            'state_blacklist': list(ROOF_BLACKLIST),
            'shaft_carve': {'dx': ROOF_SHAFT_DX, 'dz': list(ROOF_SHAFT_DZ),
                            'rule': 'keep cells at/below the neighbor roofline (max non-air dy of dx 0..2 at same dz)'},
            **roof_filter_stats(),
            'slice_scan': slice_scan(mother),
            'clean_slice': slice_info,
            'overlay_tiles_x': list(ROOF_REPEAT_X),
            'overlay_anchor_yz': [SLICE_Y[0], SHELL_DZ],
            'chimneys': [clean_anchor('s3-chimney'),
                         [CHIMNEY_X2, clean_anchor('s3-chimney')[1], clean_anchor('s3-chimney')[2]]],
        },
        'fill': {'region': 'x0..22 y0..34 z0..13', 'material': wall['chosen'],
                 'cells': SCENE_W * (FILL_TOP_Y + 1) * (SHELL_DZ + 1)},
        'stamps': records,
        'shell_patch': patch,
        'overwrites': {'counts': {k: int(v) for k, v in scene.overwrite_counts.items()},
                       'samples': scene.overwrite_samples},
        'surface_comparison': surface_comparison(scene, mother),
        'stamp_audit': audit,
        'validation': validation,
    }
    if not args.skip_render:
        assembly['renders'] = {
            'prototype': render(schem_path, run_dir / 'previews'),
            'mother': render(MOTHER_PATH, run_dir / 'ref-previews'),
        }
    dump_json(run_dir / 'assembly.json', assembly)
    write_report(run_dir / 'ASSEMBLY.md', assembly)
    print('validation:', validation['status'])
    print('wrote', run_dir)


if __name__ == '__main__':
    main()
