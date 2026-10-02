"""Building1 (巴黎建筑素材1, civic/monumental) element-level decomposition -> library-v4/atlas-techniques.

Same lossless pipeline as tools/decompose_street1.py: source-crop keeps original
DataVersion and states; detail only trims all-air padding, compacts the palette and
applies explicit chain->iron_chain renames via migrate_to_12111. Door halves, stair
shapes and wall/rail connection states are preserved as source evidence.

Usage (from paris-builder/, PYTHONPATH=src):
    python -X utf8 tools/decompose_building1.py --render [--only id ...]
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
SOURCE_PATH = ROOT.parent / '巴黎建筑素材' / '巴黎建筑素材1.schem'
SOURCE_ID = 'building1'
SOURCE_REL = '巴黎建筑素材/巴黎建筑素材1.schem'
VIEWS = ['front', 'back', 'left', 'right', 'top', 'axonometric_front', 'axonometric_back']

MODDED_NOTE = '含未转译模组方块：仅保留源证据，排除原版直接装配；预览中的替代模型不算原模型验证。'
VANILLA_NOTE = '目标版本方块注册表通过；装配与游戏行为尚需验证。'

PARTS = [
    {
        'id': 'b1-corner-pavilion-body', 'bbox': [0, 0, 4, 27, 31, 25],
        'title': '素材1 · 西北角亭主体段（拱廊基座+巨柱贵族层）',
        'families': ['rustication', 'quoin', 'pilaster', 'window_surround', 'balustrade', 'arch'],
        'outside': 'north/-z + west/-x',
        'observation': '角亭主体两面（北/西）对称华丽：底层凹砌粗石墩夹圆拱洞（铁门扇深衬+干草块拱肩金垫），y10 链条饰带与 y11 红饰带贯通；'
                       '其上巨型壁柱（2宽砂岩柱身+棕色竖槽+干草块柱头，部分柱身为 create 方解石墙）夹通高长窗'
                       '（前后两层铁门薄窗面+白框+车刻章饰窗顶+窗台石板阳台）；转角棱为凹凸砌缝垛。',
        'constraint': '角亭价值在北/西两面交接与巨柱贯通，复用时整面搬移，不把两面压到同一平面；'
                      '含 create 方解石壁柱，原版装配需替换为白色墙类方块；顶部阳台带在 y31 由顶帽段接续。',
        'finding': '主体段两面可读：每面拱廊基座、巨柱长窗层、链饰带与红饰带完整，转角砌缝垛与顶部阳台起头保留。',
    },
    {
        'id': 'b1-corner-pavilion-cap', 'bbox': [0, 31, 4, 27, 55, 25],
        'title': '素材1 · 西北角亭顶帽段（陡金字塔顶+望楼平台+尖顶饰）',
        'families': ['roof_slope', 'dormer', 'finial', 'balustrade', 'roof_ornament'],
        'outside': 'north/-z + west/-x',
        'observation': '转角纪念化的核心段：主体檐口栏干之上拔起陡峻金字塔形石板顶（深板岩砖/瓦/凝灰岩/灰混凝土粉杂混+墙钉肌理），'
                       '各坡面开金色小老虎窗；顶收为望楼平台——石栏干围合、金色望柱、两颗黑球尖顶饰（栅栏柱+深色球）、中央小阁，'
                       '是市政类"转角拔高+独立顶冠"做法的完整样本。',
        'constraint': '顶帽依赖下方巨柱的竖向贯通作支撑逻辑，单独截取屋顶会失去纪念化依据；'
                      '老虎窗与坡面绑定，不可平移到檐口；平台尖顶饰为整组栏杆+望柱+黑球，勿只取黑球。',
        'finding': '顶帽段完整：金字塔顶四坡、坡面老虎窗、望楼平台栏干与双黑球尖顶饰均在件内，两面檐口回转可见。',
    },
    {
        'id': 'b1-tower-center-shaft', 'bbox': [160, 36, 50, 184, 64, 74],
        'title': '素材1 · 东翼中央钟楼基座段（曼萨德台地+石砌塔身）',
        'families': ['roof_ornament', 'balustrade', 'window_surround', 'quoin', 'dormer'],
        'outside': 'east/+x',
        'observation': '东翼中央大曼萨德自街面檐口陡起（坡面带两只金框老虎窗），顶收为石板平台，'
                       '平台周圈屋脊栏干（石板压顶+金柱+链栏+黑玫尖饰）；中央升起石砌塔身'
                       '（深板岩系+圆石杂混、转角隅石、东面金色凸窗配小阳台），塔身顶部外挑一周转角阳台，'
                       '是穹顶/钟楼下段的标准做法。',
        'constraint': '塔身立在曼萨德平台中轴上，与 b1-tower-center-crown 上下叠合使用（y63 处搭接一格）；'
                      '平台栏干与南北坡面在裁切边界冻结，延续段在东翼屋面。',
        'finding': '基座段完整：曼萨德台地与两只坡面老虎窗、周圈脊栏、石砌塔身与金色凸窗、顶部挑阳台均在件内。',
    },
    {
        'id': 'b1-tower-center-crown', 'bbox': [168, 63, 57, 179, 82, 68],
        'title': '素材1 · 东翼中央钟楼顶冠（开敞柱廊亭+叠涩尖顶）',
        'families': ['finial', 'roof_ornament', 'arch'],
        'outside': 'east/+x',
        'observation': '塔身阳台之上：石板基盘承开敞柱廊亭（金栅栏柱+链条栏板+石板顶盖），其上第二层收分鼓座'
                       '（石砌+金饰件+白点缀），再叠涩出尖顶——深板岩细针配金色环节、横臂、球饰，顶端单格杆至 y81 收头，'
                       '是市政塔楼"亭-座-针"三段收头样本。',
        'constraint': '尖顶各段（柱廊亭/鼓座/针）竖向对位不可错位；与 b1-tower-center-shaft 在 y63 搭接一格叠合；'
                      '链条栏板连接状态冻结，粘贴须关闭方块更新。',
        'finding': '顶冠完整：柱廊亭、收分鼓座、叠涩尖顶与顶端杆件连续可读，基盘与塔身挑阳台对位关系保留。',
    },
    {
        'id': 'b1-pilaster-giant', 'bbox': [61, 0, 5, 65, 32, 12],
        'title': '素材1 · 贯通巨型壁柱全高段（基座到柱头）',
        'families': ['pilaster', 'rustication', 'string_course'],
        'outside': 'north/-z',
        'observation': '2宽砂岩壁柱自基座贯通至檐口：基座段为凹砌粗石墩（砂岩墙冻出砌缝），柱身嵌棕色竖槽'
                       '（去皮木/蘑菇茎竖线）并夹卵石纹横带，y10 链饰带与 y11 红饰带横穿柱身，柱头以干草块金垫+灰牙子收进檐口；'
                       '左右各带半开间窗框作参照。',
        'constraint': '巨柱是开间骨架（7宽一开间：2宽柱+5宽窗），压缩面宽时减少开间数，不把柱身竖槽挤变形；'
                      '柱脚粗石墩与柱身不可分截。',
        'finding': '全高壁柱可读：柱墩、竖槽柱身、饰带横穿、柱头金垫与檐口过渡完整，两侧半开间关系保留。',
    },
    {
        'id': 'b1-window-bay-noble', 'bbox': [56, 12, 5, 63, 23, 16],
        'title': '素材1 · 贵族层长窗开间（章饰窗顶+窗台阳台）',
        'families': ['window_surround', 'balustrade', 'sill', 'planter'],
        'outside': 'north/-z',
        'observation': '5宽开间：通高长窗为前后两层铁门薄窗面（外层朝向相对）+白框+中梃分层，窗顶车刻章饰'
                       '（灰云状章+两侧垂绿），窗台外挑白色石板阳台配灰栏板；两侧为巨柱半墩（含 create 方解石嵌条）；'
                       '下接层间红饰带，上抵夹层窗带。',
        'constraint': '薄窗面是双层铁门做法，禁止当成真实门洞开洞；章饰与窗绑定不可上移；'
                      '含 create 方解石壁柱嵌条，原版装配需替换为白色墙类方块。',
        'finding': '一完整开间：双层薄窗面、章饰、窗台阳台与两侧半墩齐全，上下饰带过渡保留。',
    },
    {
        'id': 'b1-base', 'bbox': [55, 0, 5, 70, 13, 16],
        'title': '素材1 · 拱廊基座段（双开间圆拱+凹砌墩）',
        'families': ['rustication', 'arch', 'portal', 'string_course'],
        'outside': 'north/-z',
        'observation': '两开间基座：凹砌粗石墩（砂岩墙砌缝+安山岩卵石纹带）夹圆拱洞，拱洞内缩白框与铁门扇深衬，'
                       '拱肩垫干草块金色拱腹石；y10 整条链条饰带贯通（链节横放作线脚），y11 红饰带+灰牙子收顶；'
                       '含 create 方解石壁柱嵌条。',
        'constraint': '拱洞阴影来自内缩深衬层，复用保留退进关系；链饰带为横放链条状态，粘贴须关闭方块更新；'
                      '含 create 方解石壁柱嵌条，原版装配需替换。',
        'finding': '双开间基座完整：两圆拱、三座凹砌墩、链饰带与红饰带连续可读，拱内深衬保留。',
    },
    {
        'id': 'b1-cornice', 'bbox': [55, 22, 5, 76, 34, 16],
        'title': '素材1 · 重檐口段（夹层窗顶多道线脚+栏干）',
        'families': ['cornice', 'balustrade', 'string_course', 'roof_junction'],
        'outside': 'north/-z',
        'observation': '夹层小窗（深色薄窗面+砂岩框）之上多道线脚叠出：灰牙子带、红饰带、砂岩挑檐与牛腿带逐级外挑，'
                       '顶部砂岩栏干（矮柱+深色栏板+瓮形饰+垂绿）压边；栏干后接深色石板条带与砾石露台边，'
                       '是市政类重檐口"多道叠涩+栏干收头"样本。',
        'constraint': '线脚与栏干须一起采用，不能只取最外挑一道；栏干后石板条是屋面收边，脱离栏干单放会失去支承逻辑。',
        'finding': '三开间檐口完整：夹层窗、多道叠涩线脚、瓮饰栏干与后部石板条/露台关系均在件内。',
    },
    {
        'id': 'b1-roof-section', 'bbox': [155, 24, 34, 190, 54, 48],
        'title': '素材1 · 东翼大曼萨德横剖条（双坡+平台+双脊栏）',
        'families': ['roof_slope', 'dormer', 'ridge', 'railing'],
        'outside': 'east/+x（街面）与 -x（内院）',
        'observation': '东翼屋顶全宽横剖：街面栏干起，内外两道陡坡（深板岩砖/瓦/圆石深板岩/凝灰岩/灰混凝土粉杂混出板岩肌理，'
                       '坡面布低态墙钉）对起，外坡嵌两只金框老虎窗；坡顶收为抛光安山岩板平台，两缘各一道屋脊栏干'
                       '（石板压顶+金柱+链栏+黑玫/灰锥尖饰交替），剖面内含源建筑的白色/粉色羊毛填充。',
        'constraint': '双坡-平台-双脊栏是整体做法，不可简化为单坡；老虎窗与坡面嵌合关系保留；'
                      '剖条两端为裁切面，羊毛填充为源建筑内部状态，非饰面。',
        'finding': '横剖条完整：街面栏干、内外双坡、两只老虎窗、平台与双道脊栏连续可读，肌理与墙钉状态保留。',
    },
    {
        'id': 'b1-dormer-mansard', 'bbox': [170, 34, 42, 182, 46, 48],
        'title': '素材1 · 曼萨德金框老虎窗（涡卷山花型）',
        'families': ['dormer', 'pediment', 'window_surround', 'planter'],
        'outside': 'east/+x',
        'observation': '2宽金框老虎窗嵌在曼萨德外坡：白色窗面（方解石/蜂巢+金色横竖梃）朝街，橡木门薄板作两侧颊板，'
                       '窗顶蘑菇茎涡卷断山花+南瓜蔓垂饰，蜂巢与枯角珊瑚扇作点缀，小板顶收头；'
                       '窗脚立坡面并以金柱支撑，是"老虎窗纪念化"做法。',
        'constraint': '老虎窗位置由坡面决定，整件含根部坡面咬合段；颊板门叶 half 状态保留，粘贴须关闭方块更新。',
        'finding': '老虎窗完整：窗面、颊板、涡卷山花、垂饰、顶帽与坡面咬合段均在件内。',
    },
    {
        'id': 'b1-cresting', 'bbox': [163, 43, 36, 178, 52, 46],
        'title': '素材1 · 屋脊栏干与尖顶饰段（曼萨德平台双缘）',
        'families': ['railing', 'finial', 'ridge'],
        'outside': 'roof',
        'observation': '曼萨德平台两缘各一道脊栏：抛光安山岩板压顶挑边，下衬深色半砖托，金色栅栏柱+链条栏板相间，'
                       '栏上凋零玫瑰黑尖饰与灰锥尖饰交替立起；两道脊栏夹出平台走道，'
                       '是市政屋顶"可行走屋脊平台+铁艺栏尖"做法。',
        'constraint': '脊栏以平台为依托，整件含平台面；链条栏板与栅栏柱连接状态冻结，粘贴须关闭方块更新；'
                      '黑玫尖饰是植物方块，替换会改变质感。',
        'finding': '脊栏段完整：双缘栏干、尖饰交替节奏、平台走道与檐部托板连续可读。',
    },
    {
        'id': 'b1-entry', 'bbox': [85, 0, 5, 106, 36, 14],
        'title': '素材1 · 北面中央入口与山花（门洞-巨拱窗-山花同轴）',
        'families': ['portal', 'arch', 'pediment', 'window_surround'],
        'outside': 'north/-z',
        'observation': '中央凸出体全高段：底层凹砌拱框大门洞（深色门膛+双扇木门+石门坎），其上两层贯通巨拱长窗'
                       '（白框+铁门薄窗面+横排链饰，两侧巨柱含 create 方解石嵌条），顶以中央阁楼徽饰收头'
                       '（涡卷+垂饰+纹章位）；中轴关系为 门洞-巨窗-山花 一线，是市政主入口的标准纪念化做法。',
        'constraint': '三者同轴不可错位；凸出体比两翼前挑，复用时保持进退关系；'
                      '含 create 方解石壁柱嵌条，原版装配需替换；山花后方金冠烟囱另属屋顶烟囱件，不入本件。',
        'finding': '中央入口全高可读：大门洞、巨拱长窗、阁楼徽饰与凸出体进退关系完整，两侧开间过渡保留。',
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
    data = load_schematic(SOURCE_PATH)
    source_meta = {'id': SOURCE_ID, 'path': SOURCE_REL, 'name': SOURCE_PATH.name, 'sha256': digest(SOURCE_PATH),
                   'data_version': data.data_version, 'dimensions_whd': [data.width, data.height, data.length],
                   'nonair': int(data.nonair_mask().sum()), 'air_palette_ids': data.air_ids.tolist(),
                   'class': 'civic/monumental ring block around courtyard; ornate faces all around',
                   'layout_note': '回字形环院：北翼 z6-22、南翼 z102-116、西翼 x1-23、东翼 x160-189；四角角亭拔高（西北/西南最高，尖顶饰至 y54），'
                                  '东翼中央大曼萨德+钟楼（塔身 z59-65，尖顶至 y81）；南北立面中央凸出体带门洞与山花；'
                                  '北翼屋顶为砾石露台+浅蓝玻璃筒拱，东翼为大曼萨德。'}
    OUT.mkdir(parents=True, exist_ok=True)
    records = []
    for part in PARTS:
        if args.only and part['id'] not in args.only:
            saved = OUT / part['id'] / 'record.json'
            if saved.exists():
                records.append(json.loads(saved.read_text(encoding='utf-8')))
            continue
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
            'source': SOURCE_REL, 'source_id': SOURCE_ID, 'source_sha256': source_meta['sha256'],
            'source_bbox_xyz_half_open': part['bbox'], 'clean_origin_source_xyz': offset,
            'parent': SOURCE_ID, 'outside': part['outside'],
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
            'role_review': {'reviewer': 'Kimi Code visual inspection', 'reviewer_type': 'agent',
                            'decision': 'ANNOTATED_REFERENCE', 'finding': part['finding'],
                            'evidence': relative(folder / 'previews'), 'game_acceptance': 'NOT_RUN'},
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
    index = {'schema': 'atlas-techniques-v4-building1',
             'coordinate_convention': 'source-local xyz; bbox [x0,y0,z0,x1,y1,z1], upper bounds exclusive',
             'source': source_meta,
             'cleaning_policy': 'PRESERVE_SOURCE_WITH_EXPLICIT_TARGET_VERSION_RENAMES',
             'update_policy': 'PASTE_WITH_BLOCK_UPDATES_DISABLED',
             'game_acceptance': 'NOT_RUN',
             'parts': [{'id': r['id'], 'title': r['title'], 'bbox': r['source_bbox_xyz_half_open'],
                        'dimensions_whd': r['inventory']['dimensions_whd'], 'nonair': r['inventory']['nonair'],
                        'families': r['families'], 'outside': r['outside'],
                        'compatible_vanilla': r['compatible_vanilla'],
                        'schematic': r['schematic'], 'record': relative(OUT / r['id'] / 'record.json')}
                       for r in records]}
    dump_json(OUT / 'index-building1.json', index)
    print('index-building1.json:', len(records), 'parts', flush=True)


if __name__ == '__main__':
    main()
