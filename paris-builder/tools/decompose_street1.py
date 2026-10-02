"""Street1 (巴黎民居街区1) element-level technique decomposition -> knowledge/library-v4/atlas-techniques.

Same cleaning discipline as tools/decompose_reference_sources.py (library-v3):
source-crop keeps original DataVersion and states; detail only trims all-air
padding, compacts the palette and applies explicit registry renames via
migrate_to_12111. Decorative halves, stair shapes and connection directions are
preserved as source evidence.

Usage (from paris-builder/, PYTHONPATH=src):
    python -X utf8 tools/decompose_street1.py --render [--only id ...]
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
SOURCE_PATH = ROOT.parent / '巴黎建筑素材' / '巴黎民居街区1.schem'
SOURCE_ID = 'street1'
SOURCE_REL = '巴黎建筑素材/巴黎民居街区1.schem'
VIEWS = ['front', 'back', 'left', 'right', 'top', 'axonometric_front', 'axonometric_back']

MODDED_NOTE = '含未转译模组方块：仅保留源证据，排除原版直接装配；预览中的替代模型不算原模型验证。'
VANILLA_NOTE = '目标版本方块注册表通过；装配与游戏行为尚需验证。'

PARTS = [
    {
        'id': 'st1-corner-turret-base', 'bbox': [1, 1, 1, 13, 14, 15],
        'title': '街区1 · 转角塔亭基座段（西北街角）',
        'families': ['rustication', 'arch', 'quoin', 'portal'],
        'outside': 'north/-z + west/-x',
        'observation': '转角基座：转角壁柱以凹凸砌缝砂岩砌筑并贯通全高；正面（北）与西面各开一个拱门洞，门洞以深板岩砖作拱腹暗衬形成阴影深度，拱门之上各对应一扇标准层铁门薄窗；顶部为切石砂岩层间带与连续阳台带起头。',
        'constraint': '转角的价值在两面交接与贯通壁柱；做单面基座复用时应只取一面，不把两面拼到同一平面上；顶部阳台带仅起头，完整带见 st1-balcony-band。',
        'finding': '转角基座段两面可读：每面一拱一窗、贯通转角壁柱与层间带完整，顶部为阳台带起头。',
    },
    {
        'id': 'st1-corner-turret-shaft', 'bbox': [1, 14, 1, 13, 28, 15],
        'title': '街区1 · 转角塔亭主体段（贵族层与上层）',
        'families': ['window_surround', 'balustrade', 'string_course', 'planter'],
        'outside': 'north/-z + west/-x',
        'observation': '转角主体段（自下而上）：连续阳台带（桦木台面+铁栏X格栏杆+种植）与夹层矮窗，其上为贵族层高窗（双层铁门薄窗面、中部横梃分层、窗脚石栏板阳台与花箱、拉杆牛腿挑台），窗顶接红色饰板带与层间带；转角壁柱贯通全段，两面开间节奏不同。',
        'constraint': '主体段的多层划分以层间带为界，复用时整层搬移，不要把石栏板阳台剪到矮窗层下。',
        'finding': '主体段贵族层高窗、石栏板阳台、红饰板与层间带完整，转角两面节奏差异清晰可读。',
    },
    {
        'id': 'st1-corner-turret-cap', 'bbox': [1, 28, 1, 13, 47, 16],
        'title': '街区1 · 转角塔亭顶帽段（檐口与转角高屋顶亭）',
        'families': ['cornice', 'roof_slope', 'dormer', 'roof_junction'],
        'outside': 'north/-z + west/-x',
        'observation': '转角顶帽：顶层白框窗（骨块+闪长岩，转角凸出体壁柱为 create 方解石墙）之上为挑檐托臂带，檐口在转角两面回转；转角上方屋顶拔高为陡峻的深色高屋顶亭（黑石/玄武岩/灰混凝土杂混肌理），平顶收头，是转角存在的标志。',
        'constraint': '高屋顶亭依赖下方转角壁柱的竖向贯通，单独截取屋顶会失去支撑逻辑；檐口回转关系不要拆断；含 create 模组方解石墙柱，原版装配需替换为白色墙类方块。',
        'finding': '顶帽段顶层窗、挑檐带与转角高屋顶亭完整，平顶收头未被切掉，两面檐口回转可见。',
    },
    {
        'id': 'st1-corner-turret-rear', 'bbox': [1, 1, 60, 16, 50, 80],
        'title': '街区1 · 后翼端塔（全高塔亭样本）',
        'families': ['arch', 'window_surround', 'balcony_slab', 'dormer', 'roof_slope'],
        'outside': 'west/-x',
        'observation': '后翼端部拔高为一座完整塔亭：底层骨块柱拱廊，其上四层铁门薄窗与种植阳台带（每层栏板做法不同：花岗岩墙、铁栏、枯珊瑚扇），挑檐带后接深色曼萨德顶帽，西面带四组白框老虎窗，屋脊北端一排砂岩烟囱。装饰面只朝西，北东南三面为盲墙。',
        'constraint': '这是翼楼收头塔亭，装饰面朝西；放在街道转角时盲墙面不能朝向主街。',
        'finding': '全高塔身五段（拱廊/四窗层/挑檐/顶帽老虎窗/烟囱排）完整，西装饰面与三面盲墙对比清晰。',
    },
    {
        'id': 'st1-base-arcade', 'bbox': [6, 1, 2, 19, 10, 12],
        'title': '街区1 · 粗石基座拱廊段',
        'families': ['rustication', 'arch', 'portal'],
        'outside': 'north/-z',
        'observation': '主立面基座：带凹凸砌缝的砂岩壁柱夹三连拱门洞，门洞以深板岩砖作拱腹暗衬形成阴影深度，部分门洞深处有铁门扇与白玻璃背衬；顶部切石砂岩腰线与木线条收边。',
        'constraint': '拱券的阴影效果来自深色拱腹与退进关系，复用时保留暗衬层，不要把门洞填平。',
        'finding': '三连拱与壁柱、拱腹暗衬、腰线完整，右端凸出体壁柱作自然结束。',
    },
    {
        'id': 'st1-base-entry', 'bbox': [23, 1, 2, 37, 10, 12],
        'title': '街区1 · 中央入口宽拱',
        'families': ['portal', 'arch', 'rustication'],
        'outside': 'north/-z',
        'observation': '中央入口：加宽拱门洞配石板台阶与深板岩砖门膛，左侧门洞装铁栅门（铁栏栅格），小门洞配石块门槛；木腰线在整个基座顶贯通，入口上方对应立面中央凸出体（其壁柱为 create 方解石墙，伸入本件顶部）。',
        'constraint': '中央拱比普通拱宽一倍，节奏上对应上方山花与中央凸出体；移位时保持与上部中轴对齐；含 create 模组方解石墙柱，原版装配需替换。',
        'finding': '中央宽拱、台阶、门膛、左侧铁栅门洞与木腰线完整，与中央凸出体的对位关系保留。',
    },
    {
        'id': 'st1-window-bay-noble', 'bbox': [12, 13, 3, 16, 26, 11],
        'title': '街区1 · 贵族层高窗开间（带石栏板阳台）',
        'families': ['window_surround', 'balustrade', 'sill', 'planter'],
        'outside': 'north/-z',
        'observation': '贵族层开间：通高开口分上下两档，均为前后两层朝向相对的铁门薄窗面，外层按层段交替桦木活板与铁栏；两档之间以楼梯/台阶横梃带相隔，上档窗脚设铁栏+荧光地衣半透明栏板，下档窗脚为黑色压力板窗台；挑台底以拉杆牛腿承托，两侧砂岩墙墩嵌橡木按钮饰钉，窗顶为桦木板门头带。',
        'constraint': '薄窗面是双层铁门做法，禁止当成真实门洞开洞；栏板与两档高窗绑定，不可上移下挪。',
        'finding': '一完整开间：高窗双层薄窗面、石栏板阳台、牛腿挑台与两侧半墙墩齐全。',
    },
    {
        'id': 'st1-window-bay-standard', 'bbox': [12, 7, 3, 16, 13, 11],
        'title': '街区1 · 标准层窗开间',
        'families': ['window_surround', 'sill', 'quoin'],
        'outside': 'north/-z',
        'observation': '标准层开间：双层铁门薄窗面（外层朝向相对），两侧为凹凸砌缝砂岩墙墩（砂岩墙作竖向砌块），窗下切石砂岩窗台带，窗顶为木线条与上层阳台台面板。',
        'constraint': '标准层开间比贵族层矮且简单，压缩面宽时减少开间数，不把墙墩状态挤变形。',
        'finding': '一完整开间：双层薄窗面、凹凸墙墩与上下层间带过渡齐全。',
    },
    {
        'id': 'st1-balcony-band', 'bbox': [9, 11, 2, 32, 17, 10],
        'title': '街区1 · 连续阳台带（贵族层窗脚）',
        'families': ['balcony_slab', 'railing', 'bracket', 'planter'],
        'outside': 'north/-z',
        'observation': '连续阳台带：桦木板台面+深色压力板压顶+铁栏X格栏杆，栏外点缀枯珊瑚扇与凋零玫瑰作花盆；台面由花岗岩墙与拉杆牛腿承托，整条带在壁柱处断开起伏，过中央凸出体处壁柱为 create 方解石墙。',
        'constraint': '连续带应跨过多个开间保持贯通，端部在墙墩处收头；栏杆X格靠铁栏连接状态，粘贴须关闭方块更新；含 create 模组方解石墙柱，原版装配需替换。',
        'finding': '23格连续阳台带台面、栏杆、牛腿与种植点缀连续可读，两端在墙墩处结束。',
    },
    {
        'id': 'st1-cornice', 'bbox': [15, 28, 2, 38, 37, 12],
        'title': '街区1 · 主檐口段（顶层窗头与天沟）',
        'families': ['cornice', 'corbel', 'roof_junction', 'gutter'],
        'outside': 'north/-z',
        'observation': '主檐口：顶层白框窗（骨块壁柱+闪长岩面板，凸出体处为 create 方解石墙柱）之上，砂岩挑檐带以绊线钩、墙与台阶叠出X形托臂纹样，木线条压边，顶部深色天沟带承接曼萨德起坡。',
        'constraint': '托臂纹样由小构件状态叠出，须按源状态粘贴；本件含 create 模组方解石墙柱，原版装配需替换为白色墙类方块。',
        'finding': '23格主檐口托臂带、天沟与上下过渡（顶层窗头、屋面起坡）完整；模组方块已标注。',
    },
    {
        'id': 'st1-roof-section', 'bbox': [21, 30, 3, 24, 47, 46],
        'title': '街区1 · 曼萨德屋顶纵剖条',
        'families': ['roof_slope', 'ridge', 'roof_junction'],
        'outside': 'north/-z',
        'observation': '屋顶纵剖：檐沟起（前缘顶层凸出体壁柱为 create 方解石墙），陡下坡以黑石/平滑玄武岩/灰混凝土（粉）/凝灰岩杂混出板岩肌理，中部坡折转缓上坡，屋脊以安山岩/圆石半砖平压顶，后坡对称下泄至后檐沟；两列老虎窗夹在剖条两侧作参照。',
        'constraint': '坡折位置与两坡材料肌理是曼萨德的关键，不可简化为单坡；剖条不含老虎窗本体，老虎窗另见专件；含 create 模组方解石墙柱，原版装配需替换。',
        'finding': '纵剖条完整展示檐沟-陡坡-坡折-缓坡-屋脊-后坡，两侧老虎窗未被切开。',
    },
    {
        'id': 'st1-dormer-lower', 'bbox': [12, 32, 8, 16, 39, 14],
        'title': '街区1 · 下排老虎窗（白色小平顶）',
        'families': ['dormer', 'window_surround'],
        'outside': 'north/-z',
        'observation': '下排老虎窗：白色安山岩台阶小平顶+安山岩墙白框，铁门暗窗，窗台为黑色压力板+铁栏，栏外点缀凋零玫瑰；嵌入陡坡脚，头顶即上排老虎窗。',
        'constraint': '与上排老虎窗共用同一竖向窗轴，上下成组布置；单件截取时注意上方还有一排。',
        'finding': '下排老虎窗平顶、白框、暗窗与窗台种植完整，坡脚嵌入关系清晰。',
    },
    {
        'id': 'st1-dormer-upper', 'bbox': [12, 37, 10, 16, 44, 17],
        'title': '街区1 · 上排老虎窗（白色高窗亭）',
        'families': ['dormer', 'window_surround'],
        'outside': 'north/-z',
        'observation': '上排老虎窗：安山岩墙板白颊的高窗亭，铁门深色窗面带白色竖梃背衬，黑色压力板窗台，顶部自带深色小顶帽收头；立在坡折上方的缓坡中。',
        'constraint': '高窗亭落在缓坡段，位置由坡折决定；不要把它放到陡坡脚（那是下排的位置）。',
        'finding': '上排高窗亭老虎窗白颊、窗面、窗台与小顶帽完整。',
    },
    {
        'id': 'st1-dormer-pavilion', 'bbox': [22, 37, 10, 28, 44, 17],
        'title': '街区1 · 凸出体老虎窗（深色颊板变体）',
        'families': ['dormer', 'window_surround'],
        'outside': 'north/-z',
        'observation': '凸出体上方的上排老虎窗变体：窗亭形式同白色高窗亭，但颊板改用圆石深板岩墙与深板岩砖墙的深色做法，与立面凸出体的灰色面板呼应；其下方坡脚另有一只方解石框小老虎窗（已收入 st1-pediment 范围）。',
        'constraint': '深色颊板对应立面凸出体位置，普通开间上不要用深色颊板；位置同样在坡折上方的缓坡段。',
        'finding': '凸出体老虎窗深色颊板与窗亭形式完整可读；坡脚方解石小老虎窗由 st1-pediment 覆盖。',
    },
    {
        'id': 'st1-chimney-group', 'bbox': [9, 40, 13, 17, 50, 31],
        'title': '街区1 · 屋脊红烟囱墙与苔石烟囱',
        'families': ['chimney', 'chimney_cap', 'ridge'],
        'outside': 'roof',
        'observation': '屋脊段的烟囱组：棕蘑菇块与花岗岩砌成沿屋脊走高的通高红烟囱墙（兼具防火山墙作用），墙顶一排红色花盆作收头；旁侧立苔石/圆石墙烟囱杆，杆身带深色按钮与苔藓痕迹，根部有花箱种植。',
        'constraint': '红烟囱墙沿屋脊纵向延伸，截断时应保留顶列花盆收头；本件非红砖方块，红色来自蘑菇块与花岗岩材质。',
        'finding': '红烟囱墙全高、花盆收头、苔石烟囱杆与屋脊段完整。',
    },
    {
        'id': 'st1-court-face', 'bbox': [20, 1, 36, 41, 43, 46],
        'title': '街区1 · 内院立面样本（前楼后院墙）',
        'families': ['window_surround', 'string_course', 'roof_junction'],
        'outside': 'south/+z（朝内院）',
        'observation': '内院北端立面：深板岩砖基座盲墙上托浅色三段窗墙（骨块白框+铁门薄窗，三层三开间，中轴壁柱为 create 方解石墙），窗间为木纹面板与灰色线脚，顶部挑檐带+深色曼萨德与两组白框老虎窗；两侧以深色盲墙收边，与外墙华丽语汇相比内院明显克制。',
        'constraint': '内院立面用深色盲墙与简化窗墙，不要把主立面的阳台、山花搬进内院；含 create 模组方解石墙柱，原版装配需替换。',
        'finding': '内院立面基座盲墙、三段窗墙、线脚、挑檐、屋顶与老虎窗完整一段。',
    },
    {
        'id': 'st1-pediment', 'bbox': [23, 28, 2, 36, 43, 15],
        'title': '街区1 · 中央山花（骨块涡卷）',
        'families': ['pediment', 'finial', 'window_surround'],
        'outside': 'north/-z',
        'observation': '中央山花：骨块白色涡卷左右对称，砂岩阶梯山墙逐阶收分，中央铁门暗窗配白框与种植点缀，底部小栏干与挑檐带相接；山花立在中央凸出体轴线上（凸出体壁柱为 create 方解石墙），左下角还带一只方解石框坡脚小老虎窗，背后曼萨德陡坡与上排老虎窗夹峙。',
        'constraint': '山花、中央凸出体与中央入口三者同轴，复用时保持整根中轴关系；骨块涡卷是白色强调件，勿替换为普通砂岩；含 create 模组方解石墙柱，原版装配需替换为白色墙类方块。',
        'finding': '山花涡卷、阶梯山墙、中央窗、栏干与挑檐基座完整，背后屋面关系保留。',
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
                   'nonair': int(data.nonair_mask().sum()), 'air_palette_ids': data.air_ids.tolist()}
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
    index = {'schema': 'atlas-techniques-v4-street1',
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
    dump_json(OUT / 'index-street1.json', index)
    print('index-street1.json:', len(records), 'parts', flush=True)


if __name__ == '__main__':
    main()
