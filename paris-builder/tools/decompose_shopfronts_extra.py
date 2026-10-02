"""Shopfront-variant decomposition batch 2 (街区6/7 未裁店面语汇)
-> knowledge/library-v4/atlas-techniques.

Same cleaning discipline as tools/decompose_streetwalls.py: source-crop keeps
original DataVersion and states; detail only trims all-air padding, compacts the
palette and applies explicit registry renames via migrate_to_12111. Door halves,
stair shapes and connection directions are preserved as source evidence (the
door thin-window-screens and the 45-degree chamfer door placement are the core
techniques; never "fix").

Usage (from paris-builder/, PYTHONPATH=src):
    python -X utf8 tools/decompose_shopfronts_extra.py [--render] [--only id ...]
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from paris_builder.source_decomposition import (crop, encode, inventory, state_context,
                                                family_matches, migrate_to_12111)
from paris_builder.schematic import load_schematic, _plain
from paris_builder.exporter import write_schematic, dump_json
from paris_builder.fonts import node_binary
from paris_builder.preview3d import render_previews

OUT = ROOT / 'knowledge/library-v4/atlas-techniques'
SRC_DIR = ROOT.parent / '巴黎建筑素材'
SOURCES = {
    'street6': SRC_DIR / '巴黎民居街区6.schem',
    'street7': SRC_DIR / '巴黎民居街区7.schem',
}
SOURCE_REL = {sid: f'巴黎建筑素材/{p.name}' for sid, p in SOURCES.items()}

MODDED_NOTE = '含未转译模组方块：仅保留源证据，排除原版直接装配；预览中的替代模型不算原模型验证。'
VANILLA_NOTE = '目标版本方块注册表通过；装配与游戏行为尚需验证。'

PARTS = [
    {
        'id': 'st7-shopfront-warped-corner', 'src': 'street7', 'bbox': [66, 0, 44, 86, 11, 60],
        'title': '街区7 · 45°切角诡异木店面带（西北角整段）',
        'families': ['shopfront', 'diagonal_corner', 'sign_band', 'visible_interior', 'portal'],
        'outside': 'southwest/45°切角朝内院（踏步朝向 +z 与 +x 交替）',
        'observation': '45°切角店面带整段（z44-59：北端柱 + 三开间商店 + 南端柱）。切角是 1×1 阶梯对角线（Δx=-2/Δz=+2），店面模数 4 格沿对角线重复：实心墩跨（切砂岩/蘑菇茎壁柱或去皮桦木+闪长岩墙+砂岩墙三段柱身）→ A 型橱窗（诡异木门单列 y1-4 全 half=lower、facing=west——按 1.21.11 门模型，面板贴所在格东缘、大面 ±x 被黑玻璃(x-1)与墩(x+1)夹住，朝内院+z 的是 3px 门端薄棱；背后黑色染色玻璃 y1-3 + 磨制深板岩墙 y4 + 蓝潜影盒 y5，再后两列陈列层：基岩/灰釉面陶瓦/深层绿宝石矿/深层钻石矿/sculk/青色陶瓦）→ 凹入一格的入口壁龛（y1-4 真空气，y0 磁石/平滑石棋盘地面，龛内 y2 橡木栅栏小构件，龛背黑玻璃）→ B 型橱窗（同构但 facing=north，门端薄棱朝向 +x 院侧，背侧磨制深板岩墙柱 y1-4）。facing 按所在踏步的朝向二选一（踏步面朝 +z 用 facing=west、朝 +x 用 facing=north），是 45° 斜面上每扇薄窗面都正对内院的核心手法。y5 蓝潜影盒通长招牌带压顶；y6-9 上层带（黑玻璃高窗 + 管珊瑚墙扇 + 蓝混凝土竖板 + 切砂岩 + 拉杆）；y9 蘑菇茎+砂岩墙楣带；y10 切砂岩 + 桦木楼梯(half=top) + 橡木活板门檐口收头通长。',
        'constraint': 'A/B 两型橱窗的 facing 是斜面读法本体，禁止统一朝向或配对 half；壁龛空气进深是入口空间不得填实；陈列层（基岩/矿石/潜影盒）是源内容保留不是污染；切角踏步对角线与上下檐口带一起裁，不能只取一皮。',
        'finding': '整段含北端柱、三开间（墩-A窗-龛-B窗循环×3）、南端柱与 y5 招牌带、y6-9 上层带、y10 檐口，45° 斜面店面手法完整可读；与主街直面底层（深色橡木门+黑玻璃+陈列层，见 st7-facade-unit）构造不同。',
    },
    {
        'id': 'st6-shopfront-white', 'src': 'street6', 'bbox': [19, 0, 19, 33, 14, 23],
        'title': '街区6 · 白混凝土台度+蘑菇茎竖梃橱窗带（两开间段）',
        'families': ['shopfront', 'mullion', 'glass_backing', 'sign_band', 'string_course'],
        'outside': 'south/+z',
        'observation': '连续橱窗带的两开间段（墩 x19/x27/x32，地面层开洞 x20-26 与 x28-31 两个宽开间）：自内而外 z=19 白混凝土整片背墙（y0-13，远看是白色店内衬墙）、z=20 店面主层——y0-6 开洞（白混凝土墩间真开口，内部即白墙）、y7 平滑砂岩楼梯(half 交替)楣带、y8 蘑菇茎竖梃+铁活板门、y9-11 砂岩墙墩夹白染色玻璃板(z=19 面)二宽窗组+桦木活板门扇、y12 白混凝土+砂岩墙+枯气泡珊瑚墙扇带、y13 切砂岩顶带；z=21 前层小构件——铁栏(y8-11)通长、拉杆(y13)、绊线钩、枯珊瑚扇、桦木栅栏门；z=22 橡木/桦木按钮(y13)点饰。竖向分三段：y0-6 白台度大开洞、y7-13 橱窗与招牌层、y13 切砂岩收头（y14 平滑砂岩楼梯通长层间带为上一层起算，未入裁）。',
        'constraint': '白混凝土背墙与开洞的"无玻璃白店"读法依赖整片白墙，裁时背墙必须随开洞一起入件；蘑菇茎竖梃与铁栏、按钮点饰是小构件状态装饰，粘贴须关闭方块更新；墩 x19/x27/x32 是开间分隔，拼排共享。',
        'finding': '两开间段台度、楣带、竖梃窗组、前层铁栏与顶带完整，与 st6-shopfront-band（诡异木瓦楞）同排异语汇；地面层开洞无玻璃、以白墙为衬的做法与 st5-shopfront-b（玻璃后退一格+活板百叶）互为对照。',
    },
    {
        'id': 'st6-shopfront-modern', 'src': 'street6', 'bbox': [59, 0, 20, 77, 14, 23],
        'title': '街区6 · 深板岩+黑玻璃现代店面（整段十八宽）',
        'families': ['shopfront', 'portal', 'awning', 'glass_backing', 'sign_band'],
        'outside': 'south/+z',
        'observation': '现代语汇店面整段（18 宽，磨制深板岩墩 x59-61/65/70/75-76 分三开间）：z=20 主面层——y0-4 磨制深板岩墙墩间留真入口开洞（x62-63/66-69/72-73，空气贯通进店），y5-6 磨制深板岩楼梯+半砖楣（灰地毯 y5 垂边做门帘/雨棚穗），y7-10 黑色染色玻璃板四宽通长橱窗带（三开间各 4 宽，共 12 格高窗）；z=21-22 前层——拉杆(y3-4, face=wall/floor)成对做现代门拉手、灰地毯(y5)、y12 桦木半砖外挑通长阳棚、y13 铁栏女儿墙；y11-13 过渡带（去皮桦木+砂岩墙+铁活板）上接住宅层。深板岩黑灰调与白台度段（st6-shopfront-white）在同排直接相邻，是"现代店插入古典排"的样本。',
        'constraint': '拉杆当门拉手、灰地毯当雨棚穗是小构件读法关键，禁止替换；入口开洞空气贯通不得填实；黑玻璃橱窗带与深板岩墩的黑灰配色是语汇主体，与两侧古典段的衔接墩(x59)共享。',
        'finding': '三开间入口开洞、玻璃橱窗带、阳棚、拉手与女儿墙完整；整段与同排古典店面材质对比明确，注册表通过。',
    },
    {
        'id': 'st7-shopfront-wing', 'src': 'street7', 'bbox': [58, 0, 85, 69, 11, 96],
        'title': '街区7 · 西翼内院店面（金合欢窗+诡异木双门夹窗两型）',
        'families': ['shopfront', 'portal', 'visible_interior', 'sign_band', 'pilaster'],
        'outside': 'east/+x（朝内院）',
        'observation': '西翼内院面（x≈63-66 壳）店面段 z85-95，两种与主街不同的店型相邻：z86-87 金合欢橱窗（x64 黑羊毛 y1 + 去皮金合欢原木 y2-4 成对、y5 深色橡木板，x65 平滑砂岩楼梯门槛 y1 + 桦木活板 y2 + 铁活板 y4 + 磨制深板岩墙 y5，x63 蘑菇茎竖条 y5 收边）；z89-90 实心墩跨（安山岩+去皮桦木/闪长岩墙/砂岩墙柱身）；z91-94 诡异木双门凹窗店——z92-93 是 2 宽×2 深（x64-66）的凹进开间（y1-4 真空气可步入，y0 安山岩地面），后墙 x63 黑色染色玻璃板（north/south 连接态保留），板后 x62 陈列层（深层绿宝石矿/深层钻石矿/sculk/基岩/诡异菌岩）透过黑玻璃读出黄绿货架光点；开间两侧 z91/z94 的 x65 各一列诡异木门（y1-4 全 half=lower，facing=south/north 相对——面板贴在朝开间一侧、大面在凹间内可见，门后 x64 磨制深板岩墙柱 y1-4 + 蓝潜影盒 y5 横带）；x64 绊线钩(y2) 与 x65-66 角珊瑚墙扇(y4-5) 垂饰；二层 y6-8 另有一对诡异木门（z92 facing=north / z93 facing=south，全 lower）做上层薄窗面，前层 x66 管珊瑚墙扇(y6-7)+闪长岩半砖(y8)；再上层黑玻璃高窗+蓝混凝土竖板+拉杆(y8)；y9 蘑菇茎+砂岩墙楣带；y10 切砂岩+桦木楼梯(half=top)+橡木活板檐口收头。两端 z85/z95 为蘑菇茎壁柱墩跨。',
        'constraint': '金合欢原木+黑羊毛的暖色橱窗与诡异木青色系双门凹窗店是翼楼独有，禁止与主街深色橡木入口互换；凹进开间的空气是入口进深不得填实；门叶全 lower 保留；陈列层矿石/菌岩是源内容；翼楼壳与芯（安山岩）分层记录。',
        'finding': '一段内含两种翼楼独有店型+墩跨+招牌带+檐口，翼楼店面与主街（st7-facade-unit 底层）语汇差异完整可读；与 45° 切角店（st7-shopfront-warped-corner）共用蘑菇茎壁柱与蓝潜影盒招牌带，证明全街区底层是一套模数系统。',
    },
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path):
    return path.relative_to(ROOT.parent).as_posix()


def context_entities(data, bbox):
    kept = []
    for entry in data.block_entities:
        entry = _plain(entry)
        pos = entry.get('Pos', entry.get('pos'))
        if pos is not None and len(pos) == 3 and all(bbox[i] <= int(pos[i]) < bbox[i + 3] for i in range(3)):
            kept.append(entry)
    return {'block_entities_in_crop': kept, 'source_block_entity_count': len(data.block_entities),
            'policy': 'source NBT retained here as context; exported schematics carry block geometry only',
            'source_entities': _plain(data.entities)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--render', action='store_true')
    parser.add_argument('--only', nargs='*')
    args = parser.parse_args()
    catalog = json.loads((ROOT / 'knowledge/library-v1/catalog.json').read_text(encoding='utf-8'))
    loaded = {}
    source_meta = {}
    for sid, path in SOURCES.items():
        data = load_schematic(path)
        loaded[sid] = data
        source_meta[sid] = {'id': sid, 'path': SOURCE_REL[sid], 'name': path.name, 'sha256': digest(path),
                            'data_version': data.data_version, 'dimensions_whd': [data.width, data.height, data.length],
                            'nonair': int(data.nonair_mask().sum()), 'air_palette_ids': data.air_ids.tolist()}
    OUT.mkdir(parents=True, exist_ok=True)
    records = []
    for part in PARTS:
        if args.only and part['id'] not in args.only:
            saved = OUT / part['id'] / 'record.json'
            if saved.exists():
                records.append(json.loads(saved.read_text(encoding='utf-8')))
            continue
        sid = part['src']
        data = loaded[sid]
        folder = OUT / part['id']
        folder.mkdir(parents=True, exist_ok=True)
        raw, cleaned, offset, cleaning = crop(data, part['bbox'])
        original_inventory = inventory(cleaned)
        cleaned, migrations = migrate_to_12111(cleaned, offset)
        cleaning['version_migrations'] = migrations
        cleaning['changed_nonair_cells'] = len(migrations)
        cleaning['policy'] = 'PRESERVE_SOURCE_WITH_EXPLICIT_TARGET_VERSION_RENAMES'
        for filename, grid in [('source-crop.schem', raw), ('detail.schem', cleaned)]:
            volume, palette = encode(grid)
            write_schematic(folder / filename, volume, palette, name=part['id'],
                            data_version=data.data_version if filename == 'source-crop.schem' else 4671)
        read = load_schematic(folder / 'detail.schem')
        actual = np.asarray(read.id_to_state, dtype=object)[read.volume]
        transformed_equal = bool(np.array_equal(actual, cleaned))
        reverted = cleaned.copy()
        for change in migrations:
            x, y, z = change['local_xyz']
            reverted[y, z, x] = change['before']
        raw_read = load_schematic(folder / 'source-crop.schem')
        raw_grid = np.asarray(raw_read.id_to_state, dtype=object)[raw_read.volume]
        source_equal = bool(np.array_equal(raw_grid, raw))
        pad = cleaning['removed_air_padding_xyz']
        (sx, ex), (sy, ey), (sz, ez) = pad
        trimmed = raw_grid[sy:raw_grid.shape[0] - ey, sz:raw_grid.shape[1] - ez, sx:raw_grid.shape[2] - ex]
        only_documented = bool(np.array_equal(trimmed, reverted))
        if not source_equal or not transformed_equal or not only_documented:
            raise ValueError('Export changed source states: ' + part['id'])
        load_validation = read.validation()
        if load_validation['status'] != 'PASS':
            raise ValueError('Detail schematic failed load validation: ' + part['id'])
        dump_json(folder / 'source-nbt-context.json', context_entities(data, part['bbox']))
        registry = folder / 'registry.json'
        result = subprocess.run([node_binary(), str(ROOT / 'tools/validate_schematic.cjs'),
                                 str(folder / 'detail.schem'), str(registry)],
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
        check = json.loads(registry.read_text(encoding='utf-8')) if registry.exists() else {'status': 'FAIL', 'issues': [result.stderr]}
        inv = inventory(cleaned)
        vanilla = check['status'] == 'PASS'
        record = {
            'id': part['id'], 'title': part['title'], 'bbox': part['bbox'],
            'source': SOURCE_REL[sid], 'source_id': sid, 'source_sha256': source_meta[sid]['sha256'],
            'source_bbox_xyz_half_open': part['bbox'], 'clean_origin_source_xyz': offset,
            'parent': sid, 'outside': part['outside'],
            'observation': part['observation'], 'constraint': part['constraint'], 'families': part['families'],
            'inventory': inv, 'source_inventory': original_inventory, 'cleaning': cleaning,
            'state_context': state_context(data, cleaned, offset),
            'library_matches': family_matches(part['families'], inv['exact_states'], catalog),
            'schematic': relative(folder / 'detail.schem'), 'schematic_sha256': digest(folder / 'detail.schem'),
            'raw_schematic': relative(folder / 'source-crop.schem'),
            'validation': {'source_states_equal': source_equal, 'documented_transform_equal': transformed_equal,
                           'detail_differs_from_source_crop_only_at_documented_cells': only_documented,
                           'load_validation': load_validation['status'],
                           'registry_status': check['status'], 'registry_issues': check.get('issues', []),
                           'game_acceptance': 'NOT_RUN'},
            'claim_status': 'SOURCE_STATES_VERIFIED_VISUALLY_INTERPRETED',
            'role_review': {'reviewer': 'agent visual inspection', 'reviewer_type': 'agent',
                            'decision': 'ANNOTATED_REFERENCE', 'finding': part['finding'],
                            'game_acceptance': 'NOT_RUN'},
            'compatible_vanilla': vanilla,
            'compatibility_note': VANILLA_NOTE if vanilla else MODDED_NOTE,
            'entity_scope': 'block geometry only; source NBT in source-nbt-context.json',
        }
        dump_json(folder / 'record.json', record)
        if args.render:
            metadata = folder / 'previews/render_metadata.json'
            cached = json.loads(metadata.read_text(encoding='utf-8')) if metadata.exists() else {}
            if cached.get('source_sha256') != record['schematic_sha256']:
                render_previews(folder / 'detail.schem', folder / 'previews', max_size=700)
        records.append(record)
        print(part['id'], inv['dimensions_whd'], inv['nonair'], check['status'],
              'migrations', len(migrations), flush=True)
    index = {'schema': 'atlas-techniques-v4-shopfronts-extra',
             'coordinate_convention': 'source-local xyz; bbox [x0,y0,z0,x1,y1,z1], upper bounds exclusive',
             'sources': {sid: source_meta[sid] for sid in sorted({p['src'] for p in PARTS})},
             'cleaning_policy': 'PRESERVE_SOURCE_WITH_EXPLICIT_TARGET_VERSION_RENAMES',
             'update_policy': 'PASTE_WITH_BLOCK_UPDATES_DISABLED',
             'game_acceptance': 'NOT_RUN',
             'parts': [{'id': r['id'], 'title': r['title'], 'source_id': r['source_id'],
                        'bbox': r['source_bbox_xyz_half_open'],
                        'dimensions_whd': r['inventory']['dimensions_whd'], 'nonair': r['inventory']['nonair'],
                        'families': r['families'], 'outside': r['outside'],
                        'compatible_vanilla': r['compatible_vanilla'],
                        'schematic': r['schematic'], 'record': relative(OUT / r['id'] / 'record.json')}
                       for r in records]}
    dump_json(OUT / 'index-shopfronts-extra.json', index)
    print('index-shopfronts-extra.json:', len(records), 'parts', flush=True)


if __name__ == '__main__':
    main()
