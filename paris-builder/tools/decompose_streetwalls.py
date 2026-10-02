"""Street-wall (巴黎民居街区5/6/7) shopfront & thin-window-screen decomposition
-> knowledge/library-v4/atlas-techniques.

Same cleaning discipline as tools/decompose_street1.py / decompose_reference_sources.py:
source-crop keeps original DataVersion and states; detail only trims all-air padding,
compacts the palette and applies explicit registry renames via migrate_to_12111.
Door halves, stair shapes and connection directions are preserved as source evidence
(these three sources' door thin-window-screens are the core technique; never "fix").

Usage (from paris-builder/, PYTHONPATH=src):
    python -X utf8 tools/decompose_streetwalls.py [--render] [--only id ...]
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
    'street5': SRC_DIR / '巴黎民居街区5.schem',
    'street6': SRC_DIR / '巴黎民居街区6.schem',
    'street7': SRC_DIR / '巴黎民居街区7.schem',
}
SOURCE_REL = {sid: f'巴黎建筑素材/{p.name}' for sid, p in SOURCES.items()}

MODDED_NOTE = '含未转译模组方块：仅保留源证据，排除原版直接装配；预览中的替代模型不算原模型验证。'
VANILLA_NOTE = '目标版本方块注册表通过；装配与游戏行为尚需验证。'

PARTS = [
    {
        'id': 'st5-shopfront-a', 'src': 'street5', 'bbox': [50, 0, 0, 58, 11, 5],
        'title': '街区5 · 诡异木（青色）店面单元',
        'families': ['shopfront', 'sign_band', 'plinth', 'window_surround'],
        'outside': 'north/-z',
        'observation': '长排中的一个完整店面单元（两侧平滑砂岩墩分隔）：前脸 z=0 为诡异木店盒——去皮诡异菌柄(axis=z)勒脚、扭曲藤(age 15/20/22)两格垂幔、诡异栅栏门(y3，两端 open=true 折回、中间关闭)做薄橱窗梃与卷帘、y4-5 菌柄招牌带、y6 栅栏门收边；背层 z=1 诡异菌柄(axis=y)陈列背板(y0-3)，其上方 y6-7 为诡异木门薄窗面（两叶 facing 相对、全 half=lower）做夹层窗，两侧海晶石墙柱贴边；y8 砂岩楼梯/桦木活板檐口带压在店盒顶上。',
        'constraint': '店盒、招牌带与夹层薄窗面是一体单元，不要只裁前脸一皮；栅栏门 open 状态与扭曲藤 age 是造型一部分，禁止方块更新；两侧砂岩墩是单元分隔，拼排时共享。',
        'finding': '单元含店盒前脸、陈列背板、夹层薄窗面、两侧分隔墩与顶部檐口带，构造与颜色（诡异木青色系）与同排砂岩开间明显不同。',
    },
    {
        'id': 'st5-shopfront-b', 'src': 'street5', 'bbox': [40, 0, 0, 51, 9, 4],
        'title': '街区5 · 白玻璃橱窗带（折平桦木百叶）',
        'families': ['shopfront', 'shutter', 'plinth', 'mullion'],
        'outside': 'north/-z',
        'observation': '两对橱窗开间成带（x=43,44 与 x=48,49，墙墩 x=41-42/45-47/50 分隔）：橱窗=白染色玻璃板(z=1, y1-4)后退一格，前脸 z=0 为折平贴附的桦木活板门(open=true, facing east/west, y1-4)做可开百叶/折叠门板；y0 砂岩墙勒脚、y5-6 墙楣、y7 桦木楼梯披檐通长；左端 x=40 在 z=2 另有浅灰染色玻璃板第二进深（不同进深的同类橱窗）。',
        'constraint': '玻璃后退一格+活板门折平贴附是橱窗读法的关键，不要把活板门改成关闭态填平前脸；成带使用时保持 2 宽开间+墙墩的节奏。',
        'finding': '两对橱窗开间、折平百叶、玻璃背衬、勒脚与披檐完整，开间节奏与两侧墙墩分隔清晰。',
    },
    {
        'id': 'st5-shopfront-c', 'src': 'street5', 'bbox': [15, 0, 0, 23, 11, 8],
        'title': '街区5 · 桦木凹入式店门廊',
        'families': ['shopfront', 'portal', 'visible_interior', 'transom'],
        'outside': 'north/-z',
        'observation': '6 格深的凹入门廊（真开口，非薄窗面）：两侧壁从 z=0 到 z=5 整列桦木活板门(open=true 折平)贴面形成 3 宽门廊，内衬去皮云杉木柱(z=1, y0-5)；前脸 x=18,19 为空气门洞(y0-4)，y5 关闭桦木活板门楣心+砂岩楼梯楣；门廊深处 z=1-2 上部为诡异栅栏门(y6)与铁门/诡异木门薄窗面(y6-8, 全 lower)；两侧砂岩墙墩(x=16,21，内填 melon)与相邻开间分隔。',
        'constraint': '凹廊的空气进深是入口空间本体，粘贴时不得填实；活板门折平侧壁是饰面不是结构；墩内 melon 为源填充保留。',
        'finding': '凹廊全长 6 格、活板门侧壁、云杉内衬、楣与上部薄窗面完整，与店盒式（st5-shopfront-a）、橱窗式（st5-shopfront-b）构造均不同。',
    },
    {
        'id': 'st5-window-screen', 'src': 'street5', 'bbox': [3, 8, 0, 9, 18, 5],
        'title': '街区5 · 铁门薄窗面开间（双层薄窗）',
        'families': ['window_surround', 'shutter', 'string_course', 'sill'],
        'outside': 'north/-z',
        'observation': '一完整开间（x=5,6 开口，两侧各 2 宽砂岩墙墩 x=3,4 与 x=7,8）：外层 z=0 为折平贴附的铁活板门(y8-10)与桦木活板门(y12-15)百叶层；内层 z=1-2 为铁门薄窗面——两叶 facing 相对(x=5 facing=west、x=6 facing=east，全 half=lower)，下段 3 高(y8-10)、上段 4 高(y12-15)；y11 砂岩楼梯层间带、y16-17 砂岩墙+楼梯窗顶带。与街区7橡木门薄窗面（st7-window-screen-oak）同手法不同材料。',
        'constraint': '薄窗面是双层门叶构造，禁止当作真门洞开洞，也禁止配对 half 状态；活板门百叶层的 open 朝向是造型，粘贴须关闭方块更新。',
        'finding': '开间含双层铁门薄窗面、活板门百叶、层间带与两侧墙墩，铁门×732 全 lower 的手法在一开间内完整可读。',
    },
    {
        'id': 'st5-cornice', 'src': 'street5', 'bbox': [40, 24, 0, 52, 35, 6],
        'title': '街区5 · 顶部檐口与屋基收头段',
        'families': ['cornice', 'bracket', 'planter', 'roof_junction'],
        'outside': 'north/-z',
        'observation': '街墙顶部收头段（12 宽，含一开间与墩），三段叠置：y28 顶层窗带（白染色玻璃板+砂岩墙+拉杆饰），y29 窗脚花箱（橡木栅栏+枯角珊瑚墙扇）；y30 去皮桦木带+桦木楼梯挑檐、y31 去皮橡木原木带+枯脑纹珊瑚（双层檐口带夹种植）；y32 桦木半砖通长压顶，其后深板岩砖曼萨德起坡（y32-34，含深板岩砖墙续坡），坡脚内嵌白玻璃板老虎窗（z=2 玻璃板 y32-34、z=1 铁活板门格栅、桦木框+枯角珊瑚扇点缀）。',
        'constraint': '收头由小构件状态叠出（珊瑚扇朝向、拉杆附着、活板门开合），须按源状态粘贴；深色曼萨德起坡与浅色檐口带的对比是轮廓关键；本段是长排中段，两端接口需延续或另做端头设计。',
        'finding': '檐口段顶层窗带、双层檐口带、压顶与深板岩砖曼萨德起坡（含白玻璃老虎窗脚）完整，两端在开间墩处裁断。',
    },
    {
        'id': 'st6-shopfront-band', 'src': 'street6', 'bbox': [41, 0, 18, 54, 13, 25],
        'title': '街区6 · 诡异木瓦楞三板开间店面带',
        'families': ['shopfront', 'mullion', 'planter', 'sign_band'],
        'outside': 'south/+z',
        'observation': '连续店面带的一段（3 开间，去皮橡木原木柱 x=43,46,49,52 分隔，开间 3 宽）：自内而外 z=19 瓦楞背板（平滑砂岩楼梯 half=bottom/top 交替+砂岩墙竖条叠出波纹板肌理）、z=20 砂岩墙(up=true)芯墩、z=21 大垂滴叶双层绿化槽(y5,y10)、z=22 诡异木门薄窗面（facing=south、全 half=lower，y4 与 y9 两层）做橱窗与二层招牌面；y11 去皮桦木(axis=x)通长底梁收顶；带两端为去皮桦木墩(x=41,42)与砂岩墩(x=53)。',
        'constraint': '瓦楞背板靠楼梯 half 上下交替出波纹，是状态手法不可简化；诡异木门薄窗面不是真门；绿化槽在玻璃面前一层，顺序不可颠倒。',
        'finding': '3 开间店面带柱-瓦楞背板-绿化槽-薄窗面-顶梁五层齐全，连续节奏与开间分隔完整可读。',
    },
    {
        'id': 'st6-entry', 'src': 'street6', 'bbox': [53, 0, 19, 60, 13, 25],
        'title': '街区6 · 住宅入口（蜡烛壁灯门洞）',
        'families': ['portal', 'transom', 'awning', 'plinth'],
        'outside': 'south/+z',
        'observation': '2 宽门洞（x=55,56，z=21-22 空气贯通，与店面不同是真开口）：门槛 z=21 平滑砂岩楼梯(y0, half=bottom)+半砖楣(y6, type=top)，门脸 z=22 外挑平滑砂岩楼梯披檐(y6，两端 outer_left/outer_right 转角收头)；门洞两侧蜡烛竖条(x=54,57 z=22, y7-10 各 4 支)做壁灯，楣上 z=20 铁活板门(y7-10, open 折平+一扇关闭)做气窗格栅；点缀橡木栅栏、滴水石锥挂饰、桦木/橡木按钮门饰。',
        'constraint': '蜡烛竖条与滴水石锥是小构件状态装饰，缺了入口读法就散；披檐 outer 转角楼梯状态保留；门洞空气贯通不得填实。',
        'finding': '入口门洞、门槛、披檐、烛灯、气窗格栅与挂饰完整，与相邻店面带（st6-shopfront-band）的薄窗面手法区别明确。',
    },
    {
        'id': 'st7-window-screen-oak', 'src': 'street7', 'bbox': [92, 10, 37, 96, 26, 44],
        'title': '街区7 · 橡木门薄窗面开间（对照铁门版）',
        'families': ['window_surround', 'mullion', 'glass_backing', 'balcony_slab'],
        'outside': 'south/+z（朝内院）',
        'observation': '一完整开间（x=93,94 开口，壁柱 x=92,95）：主面层 z=40 橡木门薄窗面——两叶 facing 相对（x=93 facing=east/hinge=left、x=94 facing=west/hinge=right，全 half=lower），下段 7 高(y11-17 贵族层通高)、上段 3 高(y21-23)；背层 z=39 铁活板门(open=true 折平)百叶层、z=38 避雷针(powered=true)竖梃+铁活板门芯板、z=37 青色染色玻璃背衬；前层 z=41 桦木楼梯阳台板(y10)+铁栏(y11-12)与切石砂岩半砖(y19)，z=42 橡木活板门+绊线钩+链条(axis=x, y19)+枯珊瑚扇装饰屏。与铁门版（st5-window-screen 等）同手法（两叶相对全 lower 叠高成窗）不同材料：橡木暖色、配青色玻璃背衬与铜色避雷针竖梃，且装饰层进深更厚（6 层），铁门版背衬为白玻璃/实体墙。',
        'constraint': '橡木门叶同样是薄窗面不是真门；避雷针 powered=true 是源状态保留；6 层进深（装饰屏-阳台-门面-百叶-竖梃-玻璃）顺序是立面读法本体，不可压平。',
        'finding': '开间含 7+3 两段橡木薄窗面、百叶、竖梃、玻璃背衬、阳台与装饰屏共 6 层，与铁门版的材料差异和构造同构性完整可读。',
    },
    {
        'id': 'st7-facade-unit', 'src': 'street7', 'bbox': [91, 0, 36, 101, 35, 45],
        'title': '街区7 · 标准开间全高单元（入口开间+邻店开间）',
        'families': ['portal', 'window_surround', 'shopfront', 'cornice', 'string_course'],
        'outside': 'south/+z（朝内院）',
        'observation': '350 格连续街墙的一个全高单元（10 宽×35 高×9 深）：入口开间(x=93,94)与邻店开间(x=99,100)夹 4 宽墩(x=95-98)，壁柱 x=92 收边。底层：z=39 深色橡木门(全 lower, y1-4)做入口、z=38 黑色染色玻璃背衬、z=37 灰釉面陶瓦/青色陶瓦/基岩等陈列填充层（店面橱窗内容）；上层：橡木门薄窗面三段（y11-17 七高、y21-23 三高、y30-32 三高）+切石砂岩层间带(y18-20, y24-25)，背衬青色玻璃(z=37)、铁活板百叶(z=39)、避雷针竖梃(z=38)；两道阳台(z=41, y10 与 y26，桦木楼梯板+铁栏)、装饰屏(z=42, 活板门/绊线钩/链条/枯珊瑚扇)；顶部 y29 深板岩砖+半砖+橡木活板通长暗带，y30-33 深板岩砖曼萨德起坡自背侧叠上，坡脚一开间嵌老虎窗（桦木框+顶层薄窗面+南瓜藤冠）、一开间为桦木包面盲板。背侧 z=36 即街区灰色实芯体，立面是贴在芯体前的 6 层壳。',
        'constraint': '单元价值在全高剖面（底层开口-三段薄窗-两道阳台-檐口），压缩时整层搬移不挤压层内状态；底层陈列填充层是源内容保留；深色橡木入口门同样全 lower 不配对。',
        'finding': '全高单元底层开口、三段橡木薄窗面、两道阳台、层间带与檐口收头完整，6 层立面进深关系保留。',
    },
    {
        'id': 'st7-parapet', 'src': 'street7', 'bbox': [92, 28, 36, 105, 36, 45],
        'title': '街区7 · 曼萨德起坡与屋顶窗洞收头段',
        'families': ['cornice', 'parapet', 'finial', 'roof_junction'],
        'outside': 'south/+z（朝内院）',
        'observation': '顶层橡木门薄窗面(y30-32)之上的街墙收头（13 宽两开间，一开间为窗、一开间为盲板）：y28 砂岩墙+桦木半砖墙顶带；y29 深板岩砖(z=40)+深板岩砖半砖(z=41)+橡木活板门(z=42)通长暗带；y30-33 深板岩砖曼萨德起坡自背侧(z=37 楼梯 facing=north/half=bottom 逐层叠起+半砖)压上；起坡脚两开间各嵌一只屋顶窗洞——开窗间(x=93,94)：顶层橡木门薄窗面(z=40, 全 lower)+铁活板百叶(z=39)+青色陶瓦背衬(z=38)，砂岩墙颊(x=95,101)+桦木栅栏门楣(y32, in_wall/open)+桦木半砖压顶(y33)，南瓜藤茎垂蔓+桦木活板门冠(z=41, y33-34)；盲板间(x=99,100)：桦木楼梯(z=39)+栅栏门(z=40)+桦木半砖/活板门包面，深板岩砖填心。深色曼萨德与浅色墙身的对比是收头主体。',
        'constraint': '檐口楼梯的朝向与半态、栅栏门 in_wall/open 状态是轮廓关键，禁止重算；y29 暗带与顶层薄窗面的衔接关系保留，两段一起裁；盲板间的桦木包面不可当作开口。',
        'finding': '收头段墙顶带、暗带、曼萨德起坡与两只屋顶窗洞（一开一盲）完整，两开间连续可读，深色屋面与浅色墙身对比明确。',
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
    index = {'schema': 'atlas-techniques-v4-streetwalls',
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
    dump_json(OUT / 'index-streetwalls.json', index)
    print('index-streetwalls.json:', len(records), 'parts', flush=True)


if __name__ == '__main__':
    main()
