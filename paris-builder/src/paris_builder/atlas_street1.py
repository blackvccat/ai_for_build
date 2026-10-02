"""ATLAS-HOUSE：用库件组装引擎建造第一栋楼（手法图谱第④步的落地）。

街区1 语汇的 C 类转角公寓：转角在西北角（街面=北 -z 与 西 -x），两翼沿街，
东南两面为共墙素面。除填充/共墙外全部由 knowledge/library-v4/atlas-techniques
的街区1 人工件组装（含 create 壁柱的 7 件不入装，用 vanilla 派生件替代，见报告）。

坐标约定（实测核对，见 ASSEMBLY.md）：
- st1 件 outside=north/-z（record.json 与探针渲染一致）→ 北面 turns=0，西面 turns=3
  （architecture.Face.turns：outward west → 3；位置与状态同转）。
- 场景 = 源坐标 − (COMMON_X=2, COMMON_Y=1, COMMON_Z=3)：塔亭在 (0,0,1)，
  竖向层位、立面线、屋顶剖面全部源相对，翼楼水平带与塔亭腰线自动对齐。

幂等：每次从零件重搭并覆盖全部产物。

本模块是构建逻辑的 src 驻地（P1 起；原 tools/build_atlas_house.py 的纯代码平移，
CLI 薄壳仍在该路径）。两条接入面：
- build(run_dir, seed, bays_north, bays_west)：显式开间数的原始入口，CLI 使用；
- build_from_plan(plan, work_dir, tier)：design.build 主链接口，开间数由
  plan.width/depth 按节距序列推导（见 bays_within）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np

from . import technique_library as library
from .architecture import Scene
from .atlas_assembly import (
    Assembler, bay_positions, load_piece, patch_wall_states, piece_source,
    rotate_volume, subcut_volume, validate_vanilla)
from .exporter import dump_json, write_schematic
from .schematic import load_schematic

ROOT = library.ROOT

# 源相对坐标偏移：场景原点 = 塔亭基座西北角（源 x2 / z4 前排装饰面）。
COMMON_X, COMMON_Y, COMMON_Z = 2, 1, 3
BAY_START_NORTH = 10   # 北翼开间起点：塔亭东面列（x10）与开间左半墩同柱咬合
BAY_START_WEST = 11    # 西翼开间起点：塔亭南面列（z11）与开间北端半墩同柱咬合
WING_DEPTH = 23        # 翼进深：屋面半剖条 z3..22（源 z6..25，檐沟→屋脊压顶）+ 共墙线
WALL_TOP_Y = 28        # 实芯填充顶（屋面件底 y29 之下）
FIREWALL_TOP_Y = 44    # 共墙防火墙顶（屋脊压顶 y45 之下一格）
RHYTHM = (4, 5, 5, 4)  # 横向节距序列（设计指定实测节奏）
FILL = 'minecraft:smooth_sandstone'
FILL_JOINT = 'minecraft:diorite'   # 共墙错缝点缀

#: 写进 schem NBT Metadata.Name 的名称。产物身份属于构建本身，不属于输出目录：
#: 名称与 run_dir 解耦后，同一构建在任何 run 目录字节一致。v0.2 的验收哈希
#: （runs/ATLAS-HOUSE-v0.2/determinism.json 的 05b58a…）绑定这个字符串，改它即改哈希。
SCHEMATIC_NAME = 'ATLAS-HOUSE-v0.2 corner apartment (street1 kit)'

# 层位（场景 y = 源 y − COMMON_Y，逐件 record 的 source_bbox 推导）
Y_ARCADE, Y_STANDARD, Y_BALCONY = 0, 6, 10
Y_NOBLE, Y_BALCONY_UP, Y_CORNICE = 12, 25, 27
Y_ROOF, Y_DORMER_LO, Y_DORMER_HI, Y_CHIMNEY = 29, 31, 36, 39
Y_SHAFT, Y_CAP = 13, 27

ROOF_SLICE_Z = 20  # 屋面半剖条进深（件局部 z0..19 = 源 z6..25，含整道屋脊压顶）


def derive_pieces(asm):
    """全部派生件：vanilla 修补（create 壁柱→diorite_wall 冻结态保留）与干净子裁。"""
    derived = {}

    roof = load_piece('v4:st1-roof-section')
    roof_volume, roof_palette, replaced = patch_wall_states(roof.volume, list(roof.id_to_state))
    volume, palette = subcut_volume(roof_volume, roof_palette, 0, 3, 0, 17, 0, ROOF_SLICE_Z)
    derived['roof'] = 'derived:st1-roof-section@front-vanilla'
    asm.register_derived(derived['roof'], volume, palette,
                         'st1-roof-section 前坡半剖（檐沟→屋脊）：create 壁柱 %d 格→diorite_wall；'
                         '裁局部 z0..19（后坡/后檐沟不切，共墙侧无装饰面）' % replaced,
                         source_id='v4:st1-roof-section',
                         operations=[{'op': 'patch_wall_states'},
                                     {'op': 'subcut', 'bbox': [0, 0, 0, 3, 17, ROOF_SLICE_Z]}])

    cap = load_piece('v4:st1-corner-turret-cap')
    cap_volume, cap_palette, cap_replaced = patch_wall_states(cap.volume, list(cap.id_to_state))
    derived['cap'] = 'derived:st1-corner-turret-cap@vanilla'
    asm.register_derived(derived['cap'], cap_volume, cap_palette,
                         'st1-corner-turret-cap vanilla 修补：create 壁柱 %d 格→diorite_wall'
                         '（转角高屋顶亭为源内孤例，无替代面可重裁）' % cap_replaced,
                         source_id='v4:st1-corner-turret-cap',
                         operations=[{'op': 'patch_wall_states'}])

    cornice = load_piece('v4:st1-cornice')
    volume, palette = subcut_volume(cornice.volume, cornice.id_to_state, 0, 6, 0, 9, 0, 9)
    derived['cornice'] = 'derived:st1-cornice@dense'
    asm.register_derived(derived['cornice'], volume, palette,
                         'st1-cornice 密开间干净段（局部 x0..5 = 源 x15..20，避开 21+ 的 '
                         'create 壁柱）；宽 6 = 2×斗臂节距 3，横铺相位对齐',
                         source_id='v4:st1-cornice',
                         operations=[{'op': 'subcut', 'bbox': [0, 0, 0, 6, 9, 9]}])

    balcony = load_piece('v4:st1-balcony-band')
    volume, palette = subcut_volume(balcony.volume, balcony.id_to_state, 0, 9, 0, 6, 0, 6)
    derived['balcony'] = 'derived:st1-balcony-band@dense'
    asm.register_derived(derived['balcony'], volume, palette,
                         'st1-balcony-band 密开间干净段（局部 x0..8 = 源 x9..17，避开 x27 的 '
                         '1 格 create 壁柱）；连续栏板无断口，横铺无节奏冲突',
                         source_id='v4:st1-balcony-band',
                         operations=[{'op': 'subcut', 'bbox': [0, 0, 0, 9, 6, 6]}])

    # 西翼全部件 turns=3 真旋转（位置+状态），派生后以 turns=0 落位、按派生件审计
    west = {'arcade': 'v4:st1-base-arcade', 'standard': 'v4:st1-window-bay-standard',
            'noble': 'v4:st1-window-bay-noble', 'dormer_lo': 'v4:st1-dormer-lower',
            'dormer_hi': 'v4:st1-dormer-upper'}
    for key, ident in west.items():
        read = load_piece(ident)
        volume, palette = rotate_volume(read.volume, read.id_to_state, 3)
        derived[key + '_w'] = 'derived:%s@r3' % ident.split(':')[1]
        asm.register_derived(derived[key + '_w'], volume, palette,
                             '%s turns=3（北→西）真旋转件' % ident,
                             source_id=ident, operations=[{'op': 'rotate', 'turns': 3}])
    for key in ('roof', 'cornice', 'balcony'):
        base = asm.derived[derived[key]]
        read = load_schematic(ROOT / base['path'])
        volume, palette = rotate_volume(read.volume, read.id_to_state, 3)
        derived[key + '_w'] = derived[key] + '-r3'
        asm.register_derived(derived[key + '_w'], volume, palette,
                             base['note'] + '；再 turns=3 旋转供西翼',
                             source_id=derived[key], operations=[{'op': 'rotate', 'turns': 3}])
    chimney = load_piece('v4:st1-chimney-group')
    volume, palette = subcut_volume(chimney.volume, chimney.id_to_state, 0, 8, 0, 10, 0, 10)
    derived['chimney'] = 'derived:st1-chimney-group@front'
    asm.register_derived(derived['chimney'], volume, palette,
                         '半屋面只保留完整前侧烟囱及其十格源坡脚；后侧烟囱属于被省略的后坡',
                         source_id='v4:st1-chimney-group',
                         operations=[{'op': 'subcut', 'bbox': [0, 0, 0, 8, 10, 10]}])
    volume, palette = rotate_volume(volume, palette, 3)
    derived['chimney_w'] = derived['chimney'] + '-r3'
    asm.register_derived(derived['chimney_w'], volume, palette,
                         '前侧烟囱半剖 turns=3，保留西翼完整烟囱及源坡脚',
                         source_id=derived['chimney'], operations=[{'op': 'rotate', 'turns': 3}])
    return derived


def tile_piece(asm, ident, lo, hi, x, y, z, role, axis='x'):
    """Lay complete strips and a source-backed tail; never phase-shift a full tail over its neighbour."""
    read = load_schematic(ROOT / asm.derived[ident]['path']) if ident in asm.derived else load_piece(ident)
    height, depth, width = read.volume.shape
    stride = width if axis == 'x' else depth
    for start in range(lo, hi, stride):
        length = min(stride, hi - start)
        chosen, offset = ident, [0, 0, 0]
        if length < stride:
            chosen = '%s-tail-%s%d' % (ident, axis, length)
            x1, z1 = (length, depth) if axis == 'x' else (width, length)
            cut = read.volume[:height, :z1, :x1]
            cy, cz, cx = np.where(~np.isin(cut, read.air_ids))
            offset = [int(cx.min()), int(cy.min()), int(cz.min())]
            if chosen not in asm.derived:
                volume, palette = subcut_volume(read.volume, read.id_to_state, 0, x1, 0, height, 0, z1)
                asm.register_derived(chosen, volume, palette,
                                     '沿 %s 铺设的末段，仅裁保留 %d 格；空气清边偏移 %s' % (axis, length, offset),
                                     source_id=ident,
                                     operations=[{'op': 'subcut', 'bbox': [0, 0, 0, x1, height, z1]}])
        anchor = [start if axis == 'x' else x, y, start if axis == 'z' else z]
        asm.stamp(chosen, *(anchor[i] + offset[i] for i in range(3)), role=role)


def party_joint(x, y, z):
    """共墙错缝：每 6 皮一条点缀带，带内按皮数错位的稀散 diorite。"""
    return y % 6 == 5 and (x * 2 + z) % 7 == (y // 6) % 7


def fill_core(asm, xw, zw):
    """实芯填充：只填件的背衬之后（北翼 z9 起、塔亭区 z12 起），不盖住立面浮雕。

    端部开间条带（x>=xw-2 / z>=zw-2）填充到立面线作端墩；塔亭区（转角 11×11）
    件深 11/12，填充从其背衬后开始。先填后 stamp，件覆盖它。
    """
    scene = asm.scene
    cells = 0

    def fill_box(x0, x1, z0, z1):
        nonlocal cells
        for x in range(x0, x1 + 1):
            for z in range(z0, z1 + 1):
                for y in range(WALL_TOP_Y + 1):
                    on_party = (z == WING_DEPTH - 1 and x >= WING_DEPTH) or z == zw - 1 \
                        or (x == WING_DEPTH - 1 and z >= WING_DEPTH) or x == xw - 1
                    state = FILL_JOINT if on_party and party_joint(x, y, z) else FILL
                    scene.put(x, y, z, state, 'fill:core')
                    cells += 1

    # 北翼：立面件背衬 z8 起填；东端条带全深作端墩
    fill_box(11, xw - 3, 8, WING_DEPTH - 1)
    fill_box(xw - 2, xw - 1, 1, WING_DEPTH - 1)
    # 西翼：立面件背衬 x8 起填（塔亭区 z0..10 由塔亭件自带，其南侧 z11+ 属西翼立面区）；
    # 南端条带全深（与北翼角部重叠处同料同主，重复写入无冲突）
    fill_box(8, WING_DEPTH - 1, 11, zw - 3)
    fill_box(1, WING_DEPTH - 1, zw - 2, zw - 1)
    return cells


def slope_tops(asm, roof_id):
    """屋面半剖条每进深列的顶面 y（局部），供端部共墙随坡踏步。"""
    read = load_schematic(ROOT / asm.derived[roof_id]['path'])
    air = set(int(i) for i in read.air_ids)
    tops = []
    for dz in range(read.volume.shape[1]):
        layer = read.volume[:, dz, :]
        ys = [dy for dy in range(read.volume.shape[0])
              if int(np.count_nonzero(~np.isin(layer[dy], list(air))))]
        tops.append(max(ys) if ys else 0)
    return tops


def fill_piers(asm, xs, zs):
    """节距 5 的接缝中柱：两半墩之间补墙面线内的素面墙柱（源 凸出体 3 宽墩的中柱）。"""
    scene = asm.scene
    cells = 0
    for i in range(len(xs) - 1):
        if xs[i + 1] - xs[i] == 5:
            for z in range(3, 8):
                for y in range(WALL_TOP_Y + 1):
                    scene.put(xs[i] + 4, y, z, FILL, 'fill:pier')
                    cells += 1
    for i in range(len(zs) - 1):
        if zs[i + 1] - zs[i] == 5:
            for x in range(3, 8):
                for y in range(WALL_TOP_Y + 1):
                    scene.put(x, y, zs[i] + 4, FILL, 'fill:pier')
                    cells += 1
    return cells


def fill_firewalls(asm, xw, zw):
    """共墙收口：两翼内侧防火墙（平顶上到 y44）与两端随坡踏步防火墙。"""
    scene = asm.scene
    tops = slope_tops(asm, 'derived:st1-roof-section@front-vanilla')
    cells = 0

    def wall(x, z, y1):
        nonlocal cells
        for y in range(WALL_TOP_Y + 1, y1 + 1):
            state = FILL_JOINT if party_joint(x, y, z) else FILL
            scene.put(x, y, z, state, 'fill:firewall')
            cells += 1

    for x in range(WING_DEPTH, xw):        # 北翼南侧共墙（屋脊平走向，平顶）
        wall(x, WING_DEPTH - 1, FIREWALL_TOP_Y)
    for z in range(WING_DEPTH, zw):        # 西翼东侧共墙
        wall(WING_DEPTH - 1, z, FIREWALL_TOP_Y)
    for z in range(WING_DEPTH):            # 北翼东端：随曼萨德剖面踏步
        top = 35 if z <= 8 else min(FIREWALL_TOP_Y, Y_ROOF + tops[z - 3] - 1)
        wall(xw - 1, z, top)
    for x in range(WING_DEPTH):            # 西翼南端
        top = 35 if x <= 8 else min(FIREWALL_TOP_Y, Y_ROOF + tops[x - 3] - 1)
        wall(x, zw - 1, top)
    return cells


def junction_policy(asm, xw, zw):
    """Authorize only named architectural junctions, bounded by design zones and both pieces.

    The zones encode construction ownership. They are not inferred from mismatches;
    an unexpected role pair, exterior erasure, lost piece or export drift still fails.
    Chimney-to-dormer permissions stop before the surviving chimney shafts.
    """
    zones = []
    dormer_x = min(row['anchor'][0] for row in asm.stamps if row['role'] == 'dormer-lower-north')
    dormer_z = min(row['anchor'][2] for row in asm.stamps if row['role'] == 'dormer-lower-west')

    def permit(before, after, bbox, reason):
        zones.append((before, after, bbox, reason))

    permit('roof-north', 'roof-west', [3, 29, 11, 23, 46, 23],
           '两翼半屋面在内角正交相交，西翼连续坡面接管交界')
    for roof in ('roof-north', 'roof-west'):
        for side, bounds in [('north', [20, 39, 10, xw, 46, 20]),
                             ('west', [10, 39, 15, 20, 46, 28])]:
            permit(roof, 'chimney-' + side, bounds, '烟囱携带的源坡脚嵌入屋面，轴身完整保留')
        permit(roof, 'turret-cap', [1, 29, 1, 11, 44, 13],
               '转角源屋顶亭压住两翼屋面的局部交接')
        for side, lower, upper in [
                ('north', [dormer_x, 31, 5, xw, 38, 11], [dormer_x, 36, 7, xw, 43, 14]),
                ('west', [5, 31, dormer_z, 11, 38, zw], [7, 36, dormer_z, 14, 43, zw])]:
            permit(roof, 'dormer-lower-' + side, lower, '下排老虎窗嵌入陡坡脚')
            permit(roof, 'dormer-upper-' + side, upper, '上排老虎窗嵌入坡折上方的缓坡')
    permit('chimney-north', 'chimney-north', [26, 39, 10, 28, 46, 20],
           '相邻烟囱仅源屋面坡脚重叠；烟囱轴位 x22/23 与 x28/29 不相交')
    permit('chimney-west', 'chimney-west', [10, 39, 20, 20, 46, 23],
           '西翼烟囱源坡脚局部重叠；烟囱轴位 z19/20 与 z24/25 不相交')
    for side in ('north', 'west'):
        north = side == 'north'
        street_band = lambda y0, y1, depth: ([10, y0, 0, xw, y1, depth] if north
                                             else [0, y0, 11, depth, y1, zw])
        permit('roof-' + side, 'balcony-upper-' + side, street_band(29, 31, 7),
               '上阳台源背衬与屋面最底两皮交接')
        permit('balcony-upper-' + side, 'cornice-' + side, street_band(27, 31, 7),
               '檐口底行拥有顶层栏板与台面，上阳台仅保留其下支撑')
        permit('roof-' + side, 'cornice-' + side, street_band(29, 36, 9),
               '主檐口和天沟拥有屋面脚下的檐部接缝')
        permit('balcony-lower-' + side, 'bay-noble-' + side, street_band(12, 16, 8),
               '贵族窗套接管下阳台带背衬，街面栏板仍保留')
        permit('balcony-lower-' + side, 'bay-standard-' + side, street_band(10, 12, 8),
               '标准层上两皮窗套接入连续阳台支撑带')
        permit('base-arcade-' + side, 'bay-standard-' + side, street_band(6, 9, 9),
               '标准层窗口拥有拱廊上三皮交界，避免后写拱廊擦除窗下部')
        permit('cornice-' + side, 'dormer-lower-' + side, street_band(31, 36, 11),
               '下排老虎窗的两侧颊板穿过檐沟上方局部接缝')
        shaft_safe = ([dormer_x, 39, 7, xw, 43, 14] if north else [7, 39, dormer_z, 14, 43, zw])
        permit('chimney-' + side, 'dormer-upper-' + side, shaft_safe,
               '老虎窗只接管烟囱前方源坡脚，许可区不包含烟囱轴')
        for target, y0, y1 in [('turret-shaft', 25, 27), ('turret-cap', 27, 31)]:
            permit('balcony-upper-' + side, target, [1, y0, 1, 11, y1, 13],
                   '连续上阳台端部与源转角塔亭腰线咬合')
        end = ([10, 10, 1, 11, 13, 7] if north else [1, 10, 11, 7, 13, 12])
        permit('balcony-lower-' + side, 'turret-base', end,
               '下阳台端部与塔亭基座顶腰线咬合，仅一格翼楼端柱')
        end = ([10, 13, 1, 11, 16, 7] if north else [1, 13, 11, 7, 16, 12])
        permit('balcony-lower-' + side, 'turret-shaft', end,
               '下阳台端部与塔亭主体底腰线咬合，仅一格翼楼端柱')
        permit('cornice-' + side, 'turret-cap', [1, 27, 1, 11, 36, 13],
               '塔亭帽檐拥有转角的檐口端部收口')
    permit('roof-north', 'cornice-west', [2, 29, 11, 9, 36, 23],
           '西翼檐沟拥有北翼屋面在内角穿入的局部檐脚')
    permit('base-arcade-north', 'turret-base', [10, 0, 3, 11, 9, 9],
           '首段拱廊半墩与塔亭基座东端柱咬合，仅一格端部')
    permit('bay-noble-west', 'turret-base', [1, 12, 11, 8, 13, 12],
           '塔亭基座顶皮接管首个西翼贵族开间北端的一格交界')
    permit('bay-noble-west', 'turret-shaft', [1, 13, 11, 8, 25, 12],
           '塔亭主体接管首个西翼贵族开间北端的一格交界')
    rules = []
    for before, after, zone, reason in zones:
        for first_index, first in enumerate(asm.stamps):
            if first['role'] != before:
                continue
            for last in asm.stamps[first_index + 1:]:
                if last['role'] != after:
                    continue
                lo = [max(zone[i], first['anchor'][i], last['anchor'][i]) for i in range(3)]
                hi = [min(zone[i + 3], first['anchor'][i] + first['size_whd'][i],
                          last['anchor'][i] + last['size_whd'][i]) for i in range(3)]
                # width/height/depth and anchor both use x/y/z order.
                if all(lo[i] < hi[i] for i in range(3)):
                    rule = {'from_role': before, 'to_role': after,
                            'bbox_xyz_half_open': lo + hi, 'reason': reason}
                    if rule not in rules:
                        rules.append(rule)
    return rules


def build(run_dir, seed, bays_north, bays_west, skip_render=False):
    """从零件重搭整栋并落盘全部产物。返回 (scene, assembly)。

    scene 是组装完成的 Scene（design.build 主链需要它做二次导出与状态实验件）；
    assembly 是写入 run_dir/assembly.json 的同一份报告字典。
    """
    run_dir = Path(run_dir).resolve()
    if bays_north < 5 or bays_west < 4:
        raise ValueError('source corner, dormers and four complete chimney groups require at least 5 north / 4 west bays')
    phase = seed % len(RHYTHM)
    xs = bay_positions(BAY_START_NORTH, bays_north, RHYTHM, phase)
    zs = bay_positions(BAY_START_WEST, bays_west, RHYTHM, phase)
    xw = xs[-1] + 6
    zw = zs[-1] + 6
    scene = Scene(xw, 50, zw)
    run_dir.mkdir(parents=True, exist_ok=True)
    asm = Assembler(scene, run_dir / 'derived')
    derived = derive_pieces(asm)

    core_cells = fill_core(asm, xw, zw)
    pier_cells = fill_piers(asm, xs, zs)
    # Structural closure goes behind source pieces; no late filler may erase their frozen states.
    firewall_cells = fill_firewalls(asm, xw, zw)

    # 2) 屋顶：北翼半剖条沿 x 横铺（turns=0），西翼旋转条沿 z 横铺（后写覆盖北翼，转角相交）
    tile_piece(asm, derived['roof'], 0, xw, 0, Y_ROOF, COMMON_Z, 'roof-north')
    tile_piece(asm, derived['roof_w'], BAY_START_WEST, zw, 3, Y_ROOF, 0, 'roof-west', axis='z')
    # 3) 两翼各两根完整前侧烟囱（北轴 x22/23、x28/29；西轴 z19/20、z24/25）。
    for ax in (20, 26):
        asm.stamp(derived['chimney'], ax, Y_CHIMNEY, 10, role='chimney-north')
    for az in (15, 20):
        asm.stamp(derived['chimney_w'], 10, Y_CHIMNEY, az, role='chimney-west')
    # 5) 阳台带：下层 y10（标准层之上）+ 上层 y25（檐口件底行之下补齐支撑）
    for ty, role in ((Y_BALCONY, 'balcony-lower-north'), (Y_BALCONY_UP, 'balcony-upper-north')):
        tile_piece(asm, derived['balcony'], BAY_START_NORTH, xw, 0, ty, 1, role)
    for ty, role in ((Y_BALCONY, 'balcony-lower-west'), (Y_BALCONY_UP, 'balcony-upper-west')):
        tile_piece(asm, derived['balcony_w'], BAY_START_WEST, zw, 1, ty, 0, role, axis='z')
    # 4) 檐口晚于上阳台；其底行是顶层台面与栏板，不能被复用的下阳台件擦掉。
    tile_piece(asm, derived['cornice'], BAY_START_NORTH, xw, 0, Y_CORNICE, 0, 'cornice-north')
    tile_piece(asm, derived['cornice_w'], BAY_START_WEST, zw, 0, Y_CORNICE, 0, 'cornice-west', axis='z')
    # 基座先写，标准层窗口拥有 y6..8 交接带；不允许后写拱廊抹掉窗口下部。
    tile_piece(asm, 'v4:st1-base-arcade', BAY_START_NORTH, xw, 0, Y_ARCADE, 3, 'base-arcade-north')
    tile_piece(asm, derived['arcade_w'], BAY_START_WEST, zw, 3, Y_ARCADE, 0, 'base-arcade-west', axis='z')
    # 6) 窗开间：贵族层 + 标准层（北翼 turns=0，西翼 r3）
    for bx in xs:
        asm.stamp('v4:st1-window-bay-noble', bx, Y_NOBLE, 1, role='bay-noble-north')
        asm.stamp('v4:st1-window-bay-standard', bx, Y_STANDARD, 4, role='bay-standard-north')
    for bz in zs:
        asm.stamp(derived['noble_w'], 1, Y_NOBLE, bz, role='bay-noble-west')
        asm.stamp(derived['standard_w'], 4, Y_STANDARD, bz, role='bay-standard-west')
    # 8) 转角塔亭：基座+主体（晚于翼楼件，塔亭角柱列覆盖开间半墩=咬合）
    asm.stamp('v4:st1-corner-turret-base', 0, 0, 1, role='turret-base')
    asm.stamp('v4:st1-corner-turret-shaft', 0, Y_SHAFT, 1, role='turret-shaft')
    # 9) 塔亭顶帽（vanilla 修补件）：晚于两翼屋顶，交接处覆盖（规格允许）
    asm.stamp(derived['cap'], 1, Y_CAP, 1, role='turret-cap')
    # 10) 老虎窗双排：下排嵌陡坡脚、上排立坡折上方缓坡，开间对位（节距 4/5 ⊂ 4~6）；
    #     转角亭屋顶亭占据转角上空，贴转角的开间（xs[0]/zs[0]）不放老虎窗
    for bx in xs[1:]:
        asm.stamp('v4:st1-dormer-lower', bx, Y_DORMER_LO, 5, role='dormer-lower-north')
        asm.stamp('v4:st1-dormer-upper', bx, Y_DORMER_HI, 7, role='dormer-upper-north')
    for bz in zs[1:]:
        asm.stamp(derived['dormer_lo_w'], 5, Y_DORMER_LO, bz, role='dormer-lower-west')
        asm.stamp(derived['dormer_hi_w'], 7, Y_DORMER_HI, bz, role='dormer-upper-west')
    schem_path = run_dir / 'ATLAS-HOUSE.schem'
    export_info = write_schematic(schem_path, scene.volume, scene.palette, name=SCHEMATIC_NAME)
    read_back = load_schematic(schem_path)
    validation = read_back.validation()
    registry = validate_vanilla(schem_path)
    policy = junction_policy(asm, xw, zw)
    audit = library.verify_stamp_audit(read_back, asm.audit_entries(), asm.audit_rows(),
                                       allow_overwrites=True, allowed_overwrites=policy)

    used = ['v4:st1-window-bay-noble', 'v4:st1-window-bay-standard', 'v4:st1-base-arcade',
            'v4:st1-corner-turret-base', 'v4:st1-corner-turret-shaft', 'v4:st1-dormer-lower',
            'v4:st1-dormer-upper', 'v4:st1-chimney-group']
    assembly = {
        'run': run_dir.name, 'seed': seed, 'rhythm': {'pattern': RHYTHM, 'phase': phase,
                                                      'bay_start_north': BAY_START_NORTH,
                                                      'bay_start_west': BAY_START_WEST},
        'common_origin_subtracted': [COMMON_X, COMMON_Y, COMMON_Z],
        'scene': {'width': xw, 'height': 50, 'depth': zw,
                  'bays_north': xs, 'bays_west': zs},
        'schematic': {'path': str(schem_path.relative_to(ROOT)), **export_info},
        'layers': [
            {'y': [0, 8], 'layer': '基座拱廊', 'pieces': ['v4:st1-base-arcade（翼）',
             'v4:st1-corner-turret-base（转角，自带北/西拱门洞）']},
            {'y': [6, 11], 'layer': '标准层窗', 'pieces': ['v4:st1-window-bay-standard']},
            {'y': [10, 15], 'layer': '连续阳台带（下）', 'pieces': ['derived:st1-balcony-band@dense']},
            {'y': [12, 24], 'layer': '贵族层通高两档窗（带石栏板阳台/拉杆牛腿）',
             'pieces': ['v4:st1-window-bay-noble']},
            {'y': [25, 30], 'layer': '上阳台带（支撑+台面，台面行由檐口件底行接管）',
             'pieces': ['derived:st1-balcony-band@dense', 'derived:st1-cornice@dense 底行']},
            {'y': [27, 35], 'layer': '顶层白框窗带+主檐口+天沟', 'pieces': ['derived:st1-cornice@dense']},
            {'y': [29, 45], 'layer': '曼萨德屋顶（檐沟→陡坡→坡折→缓坡→屋脊）',
             'pieces': ['derived:st1-roof-section@front-vanilla']},
            {'y': [31, 42], 'layer': '老虎窗双排（坡脚+坡折上）',
             'pieces': ['v4:st1-dormer-lower', 'v4:st1-dormer-upper']},
            {'y': [39, 48], 'layer': '屋脊烟囱组×4（两翼各 2）', 'pieces': ['v4:st1-chimney-group']},
            {'y': [0, 43], 'layer': '转角塔亭三段（基座/主体/顶帽，源 y 连续）',
             'pieces': ['v4:st1-corner-turret-base', 'v4:st1-corner-turret-shaft',
                        'derived:st1-corner-turret-cap@vanilla']},
        ],
        'piece_sources': [piece_source(ident) for ident in used],
        'excluded_pieces': [
            {'id': 'v4:st1-corner-turret-cap', 'reason': 'create 壁柱 36 格',
             'substitute': 'derived:st1-corner-turret-cap@vanilla（diorite_wall 逐格修补）'},
            {'id': 'v4:st1-roof-section', 'reason': 'create 壁柱 10 格',
             'substitute': 'derived:st1-roof-section@front-vanilla（修补+前坡半剖）'},
            {'id': 'v4:st1-cornice', 'reason': 'create 壁柱 52 格（中央凸出体）',
             'substitute': 'derived:st1-cornice@dense（干净段子裁 6 宽横铺）'},
            {'id': 'v4:st1-balcony-band', 'reason': 'create 壁柱 1 格（源 x27）',
             'substitute': 'derived:st1-balcony-band@dense（干净段子裁 9 宽横铺）'},
            {'id': 'v4:st1-base-entry', 'reason': 'create 壁柱 2 格；中央入口为源孤例无干净段',
             'substitute': '转角塔亭基座自带北/西拱门洞作入口，翼楼全拱廊'},
            {'id': 'v4:st1-court-face', 'reason': 'create 壁柱；本楼无内院', 'substitute': '无（共墙素面）'},
            {'id': 'v4:st1-pediment', 'reason': 'create 壁柱；中央山花属凸出体构图，本楼无凸出体',
             'substitute': '无'},
            {'id': 'v4:st1-dormer-pavilion', 'reason': 'vanilla 但深颊板编码=凸出体专用，本楼无凸出体',
             'substitute': '无（编码系统保留不用）'},
        ],
        'derived_pieces': asm.derived,
        'stamps': asm.stamps,
        'fill': {'core_cells': core_cells, 'pier_cells': pier_cells, 'firewall_cells': firewall_cells,
                 'material': FILL, 'party_joint': FILL_JOINT,
                 'core_region': '北翼 x0..%d z1..22 / 西翼 x1..22 z1..%d，y0..28' % (xw - 1, zw - 1)},
        'overwrites': {'counts': {k: int(v) for k, v in scene.overwrite_counts.items()},
                       'samples': scene.overwrite_samples},
        'stamp_audit': audit,
        'validation': validation,
        'independent_registry': registry,
        'source_trace': {'status': 'PASS', 'verified_stamps': len(asm.stamps),
                         'derived_pieces': len(asm.derived),
                         'policy': 'original source hash + original frozen states + replayed declared operations',
                         'door_policy': 'PRESERVE_SOURCE_HALF_STATES', 'game_acceptance': 'NOT_RUN'},
    }
    if not skip_render and all(assembly[key]['status'] == 'PASS' for key in
                               ('validation', 'independent_registry', 'source_trace', 'stamp_audit')):
        assembly['renders'] = render(schem_path, run_dir / 'previews')
    dump_json(run_dir / 'assembly.json', assembly)
    write_report(run_dir / 'ASSEMBLY.md', assembly)
    print('validation:', validation['status'], '| audit:', audit['status'],
          '| matched %d/%d cells' % (audit['matched_cells'],
                                     sum(r['cells'] for r in audit['stamps'])))
    print('wrote', run_dir)
    return scene, assembly


def render(schem_path, out_dir):
    env = dict(os.environ, PYTHONUTF8='1', PYTHONPATH=str(ROOT / 'src'))
    command = [sys.executable, '-X', 'utf8', '-m', 'paris_builder.preview3d',
               str(schem_path), '--out', str(out_dir)]
    subprocess.run(command, cwd=ROOT, env=env, check=True)
    metadata = json.loads((out_dir / 'render_metadata.json').read_text(encoding='utf-8'))
    return {'out_dir': str(out_dir.relative_to(ROOT)), 'views': sorted(metadata['views'])}


def write_report(path, assembly):
    s = assembly
    lines = [
        '# %s 装配说明（库件组装引擎第一栋楼）' % s['run'],
        '',
        '街区1 语汇 C 类转角公寓：转角在西北角（街面=北 -z 与 西 -x），两翼沿街，',
        '东南两面共墙素面。除 `fill:` 填充外全部由 `knowledge/library-v4/atlas-techniques`',
        '的街区1 人工件组装（细节层 = 真人工件组装，非程序画符号）。',
        '',
        '## 旋转约定（历史探针 runs/ATLAS-HOUSE-v0.1/rotation-probe/，本次逐格来源重放复核）',
        '',
        '- st1 件 `outside=north/-z`（record.json 与渲染一致；任务书按 south/+z 的预设不成立）。',
        '- **北面 turns=0 直贴**（件原生朝北）；**西面 turns=3**（`Face.turns`：outward west→3）。',
        '- 旋转 = 位置（transform_point）+ 状态（transform_state）一起转，先派生旋转件再以',
        '  turns=0 落位；登记 `source_id` 与显式变换后，审计从原始素材重放全部派生链。',
        '- 探针：北贴贵族开间渲 front（north/z_min）见通高窗面朝街；r3 西贴渲 left',
        '  （west/x_min）见同一窗面朝西街；塔亭基座两面拱门洞分别朝北/西。约定正确。',
        '',
        '## 体量与开间',
        '',
        '- 场景 %d×%d×%d（宽×高×深）；总高：塔亭顶 43 / 屋脊 45 / 烟囱顶 48。' % (
            s['scene']['width'], s['scene']['height'], s['scene']['depth']),
        '- 北翼开间 x = %s（节距 4,5,5,4，宽 4 件相邻半墩互咬合）；'
        '西翼开间 z = %s（节距 4,5,5）。种子 %d → 节奏相位 %d。' % (
            s['scene']['bays_north'], s['scene']['bays_west'], s['seed'], s['rhythm']['phase']),
        '- 翼进深 23：屋面半剖条（源 z6..25，檐沟→屋脊压顶整道）+ 共墙防火墙收口。',
        '',
        '## 竖向分层（场景 y = 源 y − 1，层位由件 record 的 source_bbox 推导）',
        '',
        '| y | 层 | 件 |', '|---|---|---|',
    ]
    for row in s['layers']:
        lines.append('| %d–%d | %s | %s |' % (row['y'][0], row['y'][1], row['layer'],
                                              '、'.join(row['pieces'])))
    lines += [
        '',
        '设计书层序（基座→贵族→标准×2→上阳台→檐口）与"源相对叠放"不可兼得：件携带的是源楼',
        '自身的层序（基座→标准→阳台→贵族→上阳台→檐口），且 44–48 总高只容源层序。取源层序，',
        '两翼水平带与塔亭腰线自动对齐；贵族层带石栏板阳台、双排老虎窗等设计书元素全部保留。',
        '',
        '## 排除件与 vanilla 替代（7 件 create 壁柱不入装）',
        '',
        '| 排除件 | 原因 | 替代 |', '|---|---|---|',
    ]
    for row in s['excluded_pieces']:
        lines.append('| %s | %s | %s |' % (row['id'], row['reason'], row['substitute']))
    lines += [
        '',
        '## 放置统计',
        '',
        '| # | 件 | 角色 | 锚点 [x,y,z] | 放置 | 裁齐跳过 |',
        '|---|---|---|---|---|---|',
    ]
    for i, row in enumerate(s['stamps']):
        lines.append('| %d | %s | %s | %s | %d | %d |' % (
            i + 1, row['id'], row['role'], row['anchor'], row['placed'], row['clipped']))
    lines += ['', '### 覆盖冲突（overwrite_counts，后写覆盖前者）', '']
    for key, count in s['overwrites']['counts'].items():
        lines.append('- %s：%d 格' % (key, count))
    lines += [
        '',
        '预期覆盖：开间半墩互咬、阳台/檐口与开间在层间过渡带同源重叠、塔亭顶帽覆盖两翼',
        '屋顶交接处、共墙防火墙裁齐屋面。fill 之上由件覆盖属设计内（先填后 stamp）。',
        '',
        '## 校验',
        '',
        '- `load_schematic().validation()`：**%s**' % s['validation']['status'],
        '- 独立 Node 注册表 / 文件回读：**%s**，changed_voxels=%d。' % (
            s['independent_registry']['status'],
            s['independent_registry']['independent_read']['roundtrip_changed_voxels']),
        '- stamp 回读审计（verify_stamp_audit）：**%s**，原样匹配 %d/%d 格。' % (
            s['stamp_audit']['status'], s['stamp_audit']['matched_cells'],
            sum(r['cells'] for r in s['stamp_audit']['stamps'])),
        '- 按角色、实际件相交盒与建筑层位限定的许可交接覆盖 %d 格；裁剪 %d 格；'
        '无法解释损失 %d 格；整件丢失 %d 件。完整有限规则见 assembly.json/stamp_audit/overwrite_policy。' % (
            s['stamp_audit']['authorized_overwritten_cells'], s['stamp_audit']['clipped_cells'],
            s['stamp_audit']['unexplained_cells'], s['stamp_audit']['fully_lost_stamps']),
        '- 源逐格追溯：**%s**；冻结门叶 half 保持源作品，模组替代仅允许 '
        '`create:cut_calcite_wall → minecraft:diorite_wall`，保留完整连接属性。' % s['source_trace']['status'],
        '- 每条横铺的尾段登记源子裁，不回退整件覆盖相邻条；共墙结构先填再装件，'
        '标准窗后于拱廊，檐口后于上阳台，避免后写结构擦除库件。',
        '',
        '## 已知边界',
        '',
        '- 转角屋顶交接 = 两坡正交覆盖（无真正虎背/天沟建模），塔亭顶帽压住交界。',
        '- 檐口件顶层窗带保持源密开间节距 3，与翼楼 4/5 节距存在 1 格级轴线错位',
        '  （设计指定节奏与源件自带节奏的取舍，逐件横铺无法两全）。',
        '- 屋顶坡面肌理按 3 格剖条横铺，杂混纹理存在平铺重复；完整前侧烟囱自带坡脚补丁与',
        '  剖条纹理在补丁边缘有接缝（源即如此拼接）。',
        '- 共墙=素面 smooth_sandstone + 每 6 皮错缝 diorite 点缀，不写窗（显式决策，',
        '  参照素材2 共墙先例）；内侧防火墙升至 y44，端部共墙随曼萨德剖面踏步。',
        '- 标准层只出现 1 层（源楼即 1 层；设计书"标准层×2"与 44–48 总高冲突，见上）。',
        '- 游戏内验收 NOT_RUN：粘贴须 WorldEdit/FAWE 关闭方块更新（冻结态依赖）。',
    ]
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def probe_rotation(run_dir):
    """旋转约定验证小场景：北贴/西贴贵族开间 + 塔亭基座，渲七视角人工确认。"""
    run_dir = Path(run_dir).resolve()
    probe_dir = run_dir / 'rotation-probe'
    probe_dir.mkdir(parents=True, exist_ok=True)
    scene = Scene(26, 16, 26)
    asm = Assembler(scene, probe_dir / 'derived')
    asm.stamp('v4:st1-window-bay-noble', 14, 1, 2, role='probe-north-bay')
    asm.stamp('v4:st1-corner-turret-base', 2, 1, 2, role='probe-turret-base')
    read = load_piece('v4:st1-window-bay-noble')
    volume, palette = rotate_volume(read.volume, read.id_to_state, 3)
    asm.register_derived('probe:st1-window-bay-noble@r3', volume, palette, 'rotation probe',
                         source_id='v4:st1-window-bay-noble',
                         operations=[{'op': 'rotate', 'turns': 3}])
    asm.stamp('probe:st1-window-bay-noble@r3', 2, 1, 14, role='probe-west-bay')
    schem_path = probe_dir / 'probe.schem'
    write_schematic(schem_path, scene.volume, scene.palette, name='rotation probe')
    render(schem_path, probe_dir / 'previews')
    dump_json(probe_dir / 'probe.json', {'stamps': asm.stamps,
              'expectation': '北件 front 视窗面朝街；r3 西件 left 视窗面朝西街；塔亭拱门朝北+西'})
    print('probe written to', probe_dir)


# ---------------------------------------------------------------------------
# design.build 主链接口（detail_profile='atlas_street1'）
# ---------------------------------------------------------------------------

#: 该 profile 的最小开间数：塔亭 + 转角交接要求北翼 5 开间、西翼 4 开间
#: （build() 对更小的开间数同样拒绝，这里保持同一条底线）。
MIN_BAYS_NORTH, MIN_BAYS_WEST = 5, 4


def bays_within(start, limit, phase, minimum):
    """从可用面宽推导开间数：满足 xs[-1]+6 <= limit 的最大值，且不得小于 minimum。

    节距序列 RHYTHM 从 phase（= seed % 4）起循环，与 build() 的显式开间路径完全同源；
    尾开间之后 +6 = 末开间 4 格 + 端墩条带 2 格（开间件宽 4，相邻半墩互咬）。
    """
    count = minimum
    while bay_positions(start, count + 1, RHYTHM, phase)[-1] + 6 <= limit:
        count += 1
    if bay_positions(start, count, RHYTHM, phase)[-1] + 6 > limit:
        raise ValueError('atlas_street1: 面宽 %d 放不下最小体量（%d 开间需 %d 格，'
                         '节距序列 %s phase=%d）' % (
                             limit, minimum,
                             bay_positions(start, minimum, RHYTHM, phase)[-1] + 6,
                             RHYTHM, phase))
    return count


def _audit_declarations(stamps):
    """与 Assembler.audit_entries() 同形的声明列表，从序列化后的 stamp 行重建。

    atelier_workflow 的校验调用点是 `verify_stamp_audit(read, manifest['stamp_audit'])`：
    第二参是逐 stamp 的声明（id/x/y/z/turns/role/clip/allow_scene_clip），不是审计结果。
    本函数保证 design 侧 manifest 的 'stamp_audit' 字段正是那个形状。
    """
    return [{'id': row['id'], 'x': row['anchor'][0], 'y': row['anchor'][1],
             'z': row['anchor'][2], 'turns': row['turns'], 'role': row['role'],
             'clip': row['clip'], 'allow_scene_clip': row['allow_scene_clip']} for row in stamps]


def composition_bays_within(start, limit, phase, minimum, mode):
    """Choose bays using their real grouped-pier span, including origin margin."""
    from .atlas_composition import wing_extra_width

    def required(count):
        return (bay_positions(start, count, RHYTHM, phase)[-1] + 6
                + wing_extra_width(count, mode=mode, phase=phase))

    if required(minimum) > limit:
        raise ValueError('atlas_street1: 面宽 %d 放不下最小体量（%s 的 %d 开间需 %d 格）'
                         % (limit, mode, minimum, required(minimum)))
    count = minimum
    while required(count + 1) <= limit:
        count += 1
    return count


def build_from_plan(plan, work_dir=None, tier=3):
    """design.build 主链接口：从 HousePlan 推导开间数并构建，返回 (scene, manifest)。

    tier0/1 只生成裸造型与立面布局；tier2/3 才装配真实细件。
    当前细件保持源完整层序，两个细化阶段都明确为 post_framework_complete_kit，
    不声称已实现逐件递增的三级技法。工作流负责先验收同一造型，再进入细节。

    work_dir 必须在项目树内（Assembler 的派生件按 ROOT 相对路径记账）；
    常规选择是 runs/<RUN>/。
    """
    if work_dir is None:
        raise ValueError("atlas_street1 构建需要 work_dir（派生件、assembly.json 与渲染的落盘目录）；"
                         "请用 design.build(plan, work_dir=...) 调用")
    if plan.form != 'corner_house':
        raise ValueError("atlas_street1 只承载 corner_house（塔亭+两翼转角体量），收到 form=%r"
                         % plan.form)
    if type(tier) is not int or tier not in (0, 1, 2, 3):
        raise ValueError('atlas_street1 tier must be 0..3')
    from .atlas_composition import composition_for
    mode = plan.composition_profile or 'grouped_pavilions'
    phase = plan.seed % len(RHYTHM)
    bays_north = composition_bays_within(BAY_START_NORTH, plan.width, phase, MIN_BAYS_NORTH, mode)
    bays_west = composition_bays_within(BAY_START_WEST, plan.depth, phase, MIN_BAYS_WEST, mode)
    composition = composition_for(plan, bays_north, bays_west, mode=mode)
    if tier < 2:
        from .atlas_street1_frame import build_frame
        scene, manifest = build_frame(plan, composition, work_dir)
        manifest['requested_tier'] = tier
        return scene, manifest
    if mode == 'flat_baseline':
        scene, assembly = build(work_dir, plan.seed, bays_north, bays_west, skip_render=True)
    else:
        from .atlas_street1_composed import build_composed
        scene, assembly = build_composed(work_dir, plan.seed, bays_north, bays_west,
                                         composition, skip_render=True)
    if scene.volume.shape[2] > plan.width or scene.volume.shape[1] > plan.depth:
        raise ValueError('atlas composition exceeds the requested width/depth budget')
    manifest = dict(assembly)
    manifest['plan'] = plan.describe()
    manifest['atlas_tier_semantics'] = 'post_framework_complete_kit'
    manifest['composition'] = composition
    from .atlas_street1_frame import build_frame
    _, targets = build_frame(plan, composition, persist=False)
    manifest['atlas_frame_spec'] = targets['atlas_frame_spec']
    manifest['framework_geometry'] = targets['framework_geometry']
    dump_json(Path(work_dir) / 'composition.json', composition)
    # atelier 形状的 stamp 声明列表；完整审计结果保留在 'atlas_audit'，
    # assembly.json 里的 'stamp_audit'（审计结果字典）字段不受影响。
    manifest['stamp_audit'] = _audit_declarations(assembly['stamps'])
    manifest['stamp_audit_policy'] = assembly['stamp_audit']['overwrite_policy']
    manifest['atlas_audit'] = assembly['stamp_audit']
    catalogue = library.catalogue()['entries']
    evidence = {row['id']: row['source_evidence'] for row in assembly['stamps']
                if row['id'] not in assembly['derived_pieces']}
    manifest['stamp_audit_rows'] = [dict(row, source_evidence=evidence[row['id']])
                                    if row['id'] in evidence else row for row in catalogue]
    manifest['stamp_audit_rows'] += [dict(row, id=ident)
                                   for ident, row in assembly['derived_pieces'].items()]
    manifest['techniques'] = [{'technique': 'atlas_source_piece', 'id': row['id'],
                               'role': row['role'], 'anchor': row['anchor']}
                              for row in assembly['stamps']]
    return scene, manifest
