"""Decompose building6 (巴黎建筑素材6, B-class palace/hotel) into library-v4 atlas-techniques.

Same lossless pipeline as tools/decompose_b5b7.py: source crop, air-padding trim,
explicit chain->iron_chain rename for 1.21.11, door halves / wall+rail connection
states preserved as source evidence, roundtrip + load checks, registry validation,
seven-view previews. Output goes to knowledge/library-v4/atlas-techniques/<id>/
plus index-building6.json. Idempotent: geometry is rewritten deterministically;
previews are re-rendered only when the detail schematic hash changes.

Measured layout (probes in runs/TECHNIQUE-ATLAS-v0.1/probe_b6_*.txt via
tools/atlas_b6_probe.py, probe crops in probe_crops/b6-*):
- 素材6 (155x48x92, B-class palace around a court of honour): ceremonial axis at
  x~84 (NOT the geometric centre 77.5). South wing (z~62-87) carries the main
  palace facade on z_max: rusticated arcade base (bedrock/deepslate piers, open
  loggia, fully glazed inner wall at z=78), giant-order colonnade above a
  projecting balcony slab (2x2-plan diorite_wall columns y14-23, triple-wall
  capitals y24-26), entablature + balustrade y27-34; pedimented end pavilions
  (west: blue-green flag, east: French tricolour) projected 1-2 blocks forward.
- North wing (z~0-25): white quartz+diorite facade on z_min, three mansard roof
  blocks (y28-35, NO dormers - measured negative), brick chimneys, blind brick
  gable firewalls. West wing carries a mansard with white-framed dormers
  (x=8, y34-37). All four courtyard faces are plain sandstone ashlar with zero
  openings (measured) - all ornament is spent on the outer faces.
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
from paris_builder.source_decomposition import crop, encode, inventory, state_context, family_matches, migrate_to_12111
from paris_builder.schematic import load_schematic, _plain
from paris_builder.exporter import write_schematic, dump_json
from paris_builder.fonts import node_binary
from paris_builder.preview3d import render_previews

OUT = ROOT / 'knowledge/library-v4/atlas-techniques'
SOURCE_PATH = ROOT.parent / '巴黎建筑素材' / '巴黎建筑素材6.schem'
SOURCE_ID = 'building6'
SOURCE_REL = '巴黎建筑素材/巴黎建筑素材6.schem'
VIEWS = ['front', 'back', 'left', 'right', 'top', 'axonometric_front', 'axonometric_back']
VANILLA_NOTE = '目标版本方块注册表通过；装配与游戏行为尚需验证。'
MODDED_NOTE = '含未转译模组方块：仅保留源证据，排除原版直接装配；预览中的替代模型不算原模型验证。'

PARTS = [
    {
        'id': 'b6-colonnade-bay', 'bbox': [58, 9, 77, 68, 35, 89],
        'title': '素材6 · 南立面巨柱柱廊单开间（阳台—柱身—柱头—檐部栏干）',
        'families': ['pilaster', 'balustrade', 'window_surround', 'cornice', 'string_course'],
        'outside': 'south/+z',
        'observation': '南立面（z_max）巨柱柱廊一完整开间（开间模数 7）：2×2 平面 diorite_wall 巨柱立于菌柄'
                       '（mushroom_stem y12-13）柱础之上，柱身 y14-23 十格贯通（墙方块连接态冻结拼出圆柱面），'
                       '柱头 y24-26 由 sandstone_wall→mossy_cobblestone_wall→cobblestone_wall 三重墙叠涩；'
                       '柱间内墙（z=78-79）为去皮橡木/干草块金镶板（SO/HA 相间）+铁栏窗（y14-16）；'
                       '柱廊地板为外挑阳台板（y9-12：方解石/砂/桦木分层+黑石按钮钉板边，前缘 z84 挂枯角珊瑚扇'
                       '与橡木活板）；柱上檐部 y27-31（砂岩/骨块/闪长岩/安山岩逐层外挑），顶收栏干'
                       '（y32-34：diorite_wall+sandstone_wall 望柱+橡木活板压顶）。',
        'constraint': '柱身与柱头全部用墙类方块堆叠，连接状态全部冻结，粘贴必须关闭方块更新；'
                      '柱廊地板（阳台板）与柱间金镶板内墙是该做法的组成部分，不可只取柱子；'
                      '开间模数 7（2×2 柱+3 宽窗跨），压缩面宽时减开间数而不挤压柱身。',
        'finding': '单开间完整可读：柱础、十格柱身、三重墙柱头、金镶板内墙、铁栏窗、阳台板与檐部栏干连续，'
                   '左右各带半开间关系。',
    },
    {
        'id': 'b6-base', 'bbox': [52, 0, 77, 76, 13, 89],
        'title': '素材6 · 南立面粗石拱廊基座段（三开间凉廊+落地玻璃内墙）',
        'families': ['rustication', 'arch', 'portal', 'string_course', 'plinth'],
        'outside': 'south/+z',
        'observation': '基座段三开间（地面层 y0-8+主层起头 y9-12）：深色粗石墩（bedrock/deepslate 交替砌筑，'
                       '2 宽、中距 7）立在柱廊线（z=82-83），墩间开敞成凉廊——洞口下缘铁栏（y0-1）+灰蜡烛（y2），'
                       '洞内悬灵魂灯笼（soul_lantern+chain 吊链 y5-7，chain→iron_chain），墩面挂灯笼与垂饰；'
                       '凉廊后壁（z=78）为整面落地白玻璃格窗墙（white_stained_glass_pane+quartz/iron_block 亮子'
                       '横档+diorite_wall 窗边），其后为室内（z=77 黏土/圆石墙芯）；'
                       '主层窗带（y5-8）上接外挑阳台板（y9-12）。',
        'constraint': '"拱廊"之拱由墩顶与层线收口表达，洞口本身为矩形，勿加拱券；吊链已显式改名 iron_chain；'
                      'bedrock/deepslate 墩是深色装饰肌理而非结构门洞，洞口下缘铁栏连接态冻结；'
                      '后壁玻璃格窗墙是基座读法的一半，不可只取石墩。',
        'finding': '三开间基座完整：四座深色粗石墩、两段铁栏洞口、吊灯笼链与落地玻璃内墙连续可读，'
                   '主层窗带与阳台板起头保留。',
    },
    {
        'id': 'b6-window-bay-noble', 'bbox': [60, 0, 77, 67, 14, 85],
        'title': '素材6 · 南立面主层高窗开间（落地格窗+亮子横档+凉廊栏干）',
        'families': ['window_surround', 'window_recess', 'sill', 'balustrade'],
        'outside': 'south/+z',
        'observation': '主层（piano nobile）高窗一开间（3 宽，x62-64）：窗面在凉廊后壁 z=78——白玻璃格窗 y2-3'
                       '+quartz/iron_block 亮子横档 y4+白玻璃格窗 y5-6+diorite_wall 窗顶梁 y7；'
                       '窗外凉廊侧（z=81）挂铁栏作栏干（y7-8）并悬灵魂灯笼吊链（y5-7）；'
                       '窗上接外挑阳台板（y8-12：sand/bone_block/polished_andesite/桦木分层+黑石按钮钉板边）——'
                       '"窗在墙后、栏在柱间"的双层立面，窗面比柱廊线内退 4 格。',
        'constraint': '景深层级为 柱廊线(z=82-83)→铁栏(z=81)→窗面(z=78)，复用必须保持退进关系；'
                      '吊链已改名 iron_chain；白玻璃格窗在渲染中呈绿松石色，是薄玻璃不是实心板。',
        'finding': '一完整开间：三层窗面（格窗-横档-格窗）、窗顶梁、凉廊栏干、吊链灯与阳台板齐全，'
                   '两侧柱墩半开间关系保留。',
    },
    {
        'id': 'b6-window-bay-north', 'bbox': [67, 0, 0, 81, 32, 7],
        'title': '素材6 · 北面白立面双开间（铁门薄窗+石英壁柱+栏干檐口）',
        'families': ['window_surround', 'pilaster', 'sill', 'balustrade', 'string_course'],
        'outside': 'north/-z',
        'observation': '北面（z_min）白立面两开间（壁柱 3 宽+窗 3 宽，中距 6-7）：地面层橡木地板（y0）上'
                       '铁门薄窗（y1-4，lower+upper×3 冻结叠置）夹白玻璃格，外沿 z=0 一排橡木门薄板带（y0）；'
                       '石英壁柱（云杉/桦木柱脚 y0-7→闪长岩/石英块柱身 y8-26→mushroom_stem 柱头 y27）'
                       '夹主层长窗（y9-13 白玻璃格 5 高+snow_block 窗台 y14+方解石/石英砖窗套）'
                       '与阁楼空腹窗（y17-19、y23-25 无玻璃暗洞）；'
                       '顶部蘑菇柄线脚（y27）+桦木栅栏栏干（y29-30）+铁活板压顶（y31）。',
        'constraint': '北面语汇=石英白+闪长岩灰，与南面砂岩金是两套配色，混用时不可互换；'
                      '阁楼窗为无玻璃空腹暗洞（借深度读窗），勿补玻璃；铁门薄窗半态冻结保留，禁当真门洞。',
        'finding': '双开间完整：壁柱-窗-壁柱节奏、地面薄窗、主层长窗、阁楼暗洞与栏干檐口连续可读，'
                   '中央窄缝（x77）开间分界保留。',
    },
    {
        'id': 'b6-pavilion-body', 'bbox': [0, 0, 70, 34, 22, 92],
        'title': '素材6 · 西南端亭主体段（前挑壁柱+章饰窗+隅石收边）',
        'families': ['pilaster', 'quoin', 'window_surround', 'rustication', 'portal'],
        'outside': 'south/+z（主立面）+ west/-x（西外棱）',
        'observation': '端亭主体（x3-33，南面+西面两面）：亭身前挑——壁柱线 z=84 比巨柱柱廊线（z=82-83）'
                       '再前 1-2 格；前挑壁柱（深色粗石墩 y1-8+菌柄柱础+diorite_wall 柱身 y14-24+三重墙柱头，'
                       '模数 6）夹三窗间，窗间砂岩墙+章饰窗套（白框+垂饰），主层绿松石长窗配小阳台；'
                       '地面层深色门脸（bedrock/deepslate）与白玻璃高窗相间；西外棱（x=2-3）为转角隅石/'
                       '粗石收边，亭内腔为源有砌筑芯材（裁切面棕色填充）。',
        'constraint': '端亭前挑是读法核心（亭线 z=84 vs 柱廊线 z=82-83），复用保持进退关系；'
                      '与 b6-pavilion-cap 在 y20-21 叠合；内腔芯材为源有状态，非饰面；'
                      '柱身墙类连接态冻结，粘贴须关方块更新。',
        'finding': '端亭主体两面可读：前挑四柱三间、章饰窗套、地面门脸、西外棱隅石收边完整，'
                   '与柱廊区的衔接开间保留。',
    },
    {
        'id': 'b6-pavilion-cap', 'bbox': [0, 20, 70, 34, 48, 92],
        'title': '素材6 · 西南端亭顶帽（阁楼+三角山花+蕾丝脊饰+蓝旗杆）',
        'families': ['pediment', 'roof_ornament', 'finial', 'cornice', 'balustrade'],
        'outside': 'south/+z（主立面）+ west/-x',
        'observation': '端亭顶帽（y20-47）：檐部栏干（y32-34）之上为阁楼层（砂岩墙+灰白浮雕饰带：'
                       '珊瑚扇/按钮/墙类拼花），其上三角山花（y33-38 逐级收分，山面布灰色浮雕纹样与中央饰位），'
                       '顶缘白色蕾丝脊饰（铁栏/墙钉类细件）与角部小尖饰（acroteria）；山花后方为灰色平屋顶'
                       '（深板岩/石质）；亭中轴避雷针旗杆（lightning_rod 倒立，y40-47）挑蓝绿色旗帜'
                       '（lapis/blue_wool/dark_prismarine/warped_trapdoor 多方块拼色）——东端亭同位挂法国三色旗'
                       '（不入本件）。',
        'constraint': '山花浮雕与蕾丝脊饰是薄片构件，须整段搬移不可拆件；旗帜为多方块拼色整体；'
                      '避雷针朝下冻结态保留；与 b6-pavilion-body 在 y20-21 叠合，竖向对位不可错位。',
        'finding': '顶帽完整：阁楼饰带、三角山花、蕾丝脊饰、角饰、屋顶平台与蓝旗杆连续可读，'
                   '檐部栏干回转关系保留。',
    },
    {
        'id': 'b6-entry', 'bbox': [79, 0, 76, 90, 14, 89],
        'title': '素材6 · 南立面中轴门洞开间（柱廊虚开间+玻璃内墙）',
        'families': ['portal', 'arch', 'rustication', 'window_surround'],
        'outside': 'south/+z',
        'observation': '全楼礼仪轴线（x≈84，与庭院中轴园路对位）穿过柱廊的门洞开间：柱廊线 x83-85 三格'
                       '自地面全空（y0-7）成通道，两侧深色粗石墩（x80-81、x87-88）夹持，墩面挂灯笼；'
                       '通道内顶悬灵魂灯笼吊链（chain→iron_chain），尽端为凉廊后壁落地玻璃格窗墙（z=78）——'
                       '门洞以"空"表达，实堵为玻璃内墙，是中轴"虚开间"做法；'
                       '通道地面内埋 minecraft:light 照明方块（源有状态）。',
        'constraint': '门洞无真实门扇（通道全空+玻璃内墙封堵），勿在此补木门；礼仪轴线 x84 偏几何中心'
                      '（77.5）以东约 6.5 格，平面东西不对称是源有事实，复用不得"纠正"回中；'
                      '吊链已改名 iron_chain。',
        'finding': '中轴门洞开间完整：三格空通道、两侧粗石墩、吊链灯与尽端玻璃内墙可读，'
                   '相邻半开间（含一深色门脸墩）关系保留。',
    },
    {
        'id': 'b6-court-face', 'bbox': [52, 0, 60, 84, 28, 67],
        'title': '素材6 · 内院立面段（南翼北面素石墙）',
        'families': ['rustication', 'string_course'],
        'outside': 'north/-z（内院面）',
        'observation': '内院立面（南翼北面 z=62）一整段（32 宽×28 高）：y0-27 全高为 sandstone/smooth_sandstone'
                       '两种砂岩交替错缝的砌筑肌理墙，零开口、零线脚、零装饰，顶部平收无檐口——'
                       '与同一翼外侧（南立面）的巨柱柱廊+金镶板+章饰窗形成极端反差；'
                       '实测四面内院立面（南翼北面、北翼南面、东西翼内面）全部无窗无饰（负发现），'
                       '该源把全部装饰预算给了外面；内侧裁切面（z=66）y13 见一条深色室内楼板线，'
                       '为源有室内结构，非立面装饰。',
        'constraint': '素墙是源有做法而非未完成面，复用时不得擅自开窗加饰；两种砂岩的错缝肌理是仅有的'
                      '"装饰"，截短或接长时保持错缝规律；墙顶平收无檐口，勿与外侧檐口混接。',
        'finding': '内院立面段完整：整段素砂岩错缝墙与顶部平收边可读，与外立面语汇差异即本件主题。',
    },
    {
        'id': 'b6-cornice', 'bbox': [58, 23, 76, 79, 35, 89],
        'title': '素材6 · 南立面檐口栏干段（三重墙柱头+逐层外挑+望柱栏干）',
        'families': ['cornice', 'balustrade', 'string_course', 'roof_junction'],
        'outside': 'south/+z',
        'observation': '檐口段三开间（y23-34）：巨柱柱头（sandstone_wall y24→mossy_cobblestone_wall y25'
                       '→cobblestone_wall y26 三重墙叠涩）承檐部——sandstone y27、sandstone_wall y28、'
                       'bone_block y29（白牙子带）、diorite y30、andesite y31 逐层外挑；'
                       '顶部栏干 y32-34（diorite_wall+sandstone_wall 望柱+橡木活板压顶），'
                       '栏干前缘 z=84 挑线上挂枯角珊瑚扇（y27/30）+石按钮+砂岩楼梯反坎+橡木活板——'
                       '"柱头叠涩+多层线脚+望柱栏干"的府邸檐口；后缘为灰色平屋顶面。',
        'constraint': '柱头三重墙与檐部线脚是同一竖向序列，不可分截单取；栏干望柱为墙方块冻结连接态，'
                      '粘贴须关方块更新；与 b6-colonnade-bay 顶部同构（本件为三开间横向展开）。',
        'finding': '三开间檐口完整：柱头叠涩、多层线脚、望柱栏干与挑线挂饰连续，屋顶面收边关系保留。',
    },
    {
        'id': 'b6-roof-section', 'bbox': [49, 23, 0, 80, 38, 27],
        'title': '素材6 · 北翼曼萨德顶块纵剖（双折坡+砖烟囱+街侧栏干带）',
        'families': ['roof_slope', 'ridge', 'railing', 'finial', 'balustrade'],
        'outside': 'north/-z',
        'observation': '北翼屋顶块 A（x50-79）全剖：白色立面顶部栏干（桦木栅栏 y29-30+铁活板 y31）之后'
                       '起曼萨德双折陡坡（y28-33：deepslate 瓦/砖楼梯逐层内收——下坡陡、上坡缓、平顶），'
                       '屋面纯净无老虎窗（实测负发现）；顶块东西两端各一座红砖烟囱（bricks 砌体+橙色细节'
                       '+深色压顶，至 y35）；曼萨德坡脚街侧（z=2-5）为栏干游廊带（金/白望柱+灰板）；'
                       '东西山墙为盲砖防火墙（本件含东山墙面）。',
        'constraint': '双折坡轮廓（陡-缓-平三段）不可简化为单坡；烟囱与顶块一体，不可分截；'
                      '北翼曼萨德实测无老虎窗（老虎窗仅在西翼曼萨德，见 b6-dormer-west），复用勿在此类顶块补窗。',
        'finding': '顶块纵剖完整：双折坡轮廓、两端砖烟囱、街侧栏干带与立面顶部栏干连续可读，'
                   '坡面无窗的负发现直接可见。',
    },
    {
        'id': 'b6-dormer-west', 'bbox': [2, 29, 12, 14, 44, 21],
        'title': '素材6 · 西翼曼萨德白框老虎窗（嵌坡齐平天窗）',
        'families': ['dormer', 'window_surround', 'roof_slope', 'railing'],
        'outside': 'west/-x',
        'observation': '西翼曼萨德坡面上的白框老虎窗一樘（z15-17，3 宽，同排四樘取中段一樘）：'
                       '白玻璃格窗面（white_stained_glass_pane y34-37）嵌在深色坡面（deepslate 砖/瓦楼梯叠涩）'
                       '内、与坡面齐平，石英砖过梁（y38）收顶，窗侧 deepslate 立梃；'
                       '坡脚有铁栏栏干（y34-35，x=4）+滴石/枯角珊瑚扇点缀；'
                       '是"框白坡黑、窗面即坡面"的齐平嵌坡做法（非外凸颊板老虎窗）。',
        'constraint': '老虎窗与坡面嵌合为一体，整件含根部坡面咬合段，不可把窗框平移到檐口；'
                      '窗顶石英砖过梁以上接屋脊方向，不可倒置；铁栏与墙类连接态冻结，粘贴须关方块更新。',
        'finding': '老虎窗完整：白框窗面、立梃、过梁、坡面咬合段与坡脚栏干连续可读，上下坡面层次保留。',
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


def build_part(data, part, catalog, source_sha, render):
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
        'source': SOURCE_REL, 'source_id': SOURCE_ID, 'source_sha256': source_sha,
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
    if render:
        metadata = folder / 'previews/render_cache.json'
        cached = json.loads(metadata.read_text(encoding='utf-8')) if metadata.exists() else {}
        if cached.get('schematic_sha256') != record['schematic_sha256']:
            render_previews(folder / 'detail.schem', folder / 'previews', max_size=700)
            dump_json(metadata, {'schematic_sha256': record['schematic_sha256'], 'views': VIEWS})
    return record


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
                   'class': 'B-class palace/hotel (free-standing block around a court of honour; ornate outer faces, plain court faces)',
                   'layout_note': '回字形荣誉庭院府邸（155×48×92，礼仪轴线 x≈84 偏几何中心以东）：南翼 z62-87 为主翼——'
                                  'z_max 南立面为柱廊主立面（深色粗石墩凉廊基座+落地玻璃内墙、巨柱柱廊 y14-26、'
                                  '檐部栏干 y27-34），两端前挑端亭（西亭蓝绿旗 y40-47、东亭法国三色旗，三角山花+'
                                  '蕾丝脊饰）；北翼 z0-25 为白石英立面（z_min）+三个曼萨德顶块（y28-35，无老虎窗）'
                                  '+红砖烟囱+盲砖山墙；西翼带曼萨德与白框老虎窗（x=8，y34-37，同排四樘）；'
                                  '东翼黄色抹灰立面；内院四面全部素砂岩墙零开口（实测）；全源 603 调色板项均为 '
                                  'minecraft 原版命名空间（无模组方块），chain 仅此一种待改名项。'}
    OUT.mkdir(parents=True, exist_ok=True)
    records = []
    for part in PARTS:
        if args.only and part['id'] not in args.only:
            saved = OUT / part['id'] / 'record.json'
            if saved.exists():
                records.append(json.loads(saved.read_text(encoding='utf-8')))
            continue
        record = build_part(data, part, catalog, source_meta['sha256'], args.render)
        records.append(record)
        print(part['id'], record['inventory']['dimensions_whd'], record['inventory']['nonair'],
              record['validation']['registry_status'], 'migrations', len(record['cleaning']['version_migrations']),
              flush=True)
    index = {'schema': 'atlas-techniques-v4-building6',
             'coordinate_convention': 'source-local xyz; bbox [x0,y0,z0,x1,y1,z1], upper bounds exclusive',
             'source': source_meta,
             'cleaning_policy': 'PRESERVE_SOURCE_WITH_EXPLICIT_TARGET_VERSION_RENAMES',
             'update_policy': 'PASTE_WITH_BLOCK_UPDATES_DISABLED',
             'game_acceptance': 'NOT_RUN',
             'negative_findings': [
                 {'id': 'b6-north-mansard-dormer', 'topic': '北翼曼萨德老虎窗',
                  'finding': '实测三个曼萨德顶块坡面逐格扫描：坡面为 deepslate 瓦/砖纯净坡，'
                             '不存在任何老虎窗；全源老虎窗仅在西翼曼萨德（x=8，y34-37，同排四樘白框窗，'
                             '已取 b6-dormer-west），南翼为平屋顶亦无老虎窗。'},
                 {'id': 'b6-court-face-ornament', 'topic': '内院立面装饰',
                  'finding': '实测四面内院立面（南翼北面 z=62、北翼南面 z=24-25、西翼东面、东翼西面）'
                             '逐列扫描：除西翼北段零星铁门薄窗外全部零开口零装饰，为素砂岩错缝墙——'
                             '内院素墙是源有做法（装饰预算全给外面），非未完成面，已取 b6-court-face 为证。'},
                 {'id': 'b6-south-wooden-doors', 'topic': '南立面"木门"',
                  'finding': '南立面地面层渲染中看似深色双开木门的构件逐格核验为 bedrock/deepslate 交替'
                             '砌筑的装饰墩面，源内不存在真实木门扇；真实出入口为中轴 x83-85 三格全空通道'
                             '（尽端玻璃内墙封堵），已取 b6-entry。'},
                 {'id': 'b6-axis', 'topic': '构图轴线',
                  'finding': '全楼礼仪轴线在 x≈84（庭院中轴园路 x84-87、南立面中轴虚开间 x83-85、'
                             '北翼廊带 x38-132 中心 85），偏几何中心 77.5 以东约 6.5 格；'
                             '平面西半（x0-84）比东半（x84-155）宽，不对称是源有事实。'},
             ],
             'parts': [{'id': r['id'], 'title': r['title'], 'bbox': r['source_bbox_xyz_half_open'],
                        'dimensions_whd': r['inventory']['dimensions_whd'], 'nonair': r['inventory']['nonair'],
                        'families': r['families'], 'outside': r['outside'],
                        'compatible_vanilla': r['compatible_vanilla'],
                        'schematic': r['schematic'], 'record': relative(OUT / r['id'] / 'record.json')}
                       for r in records]}
    dump_json(OUT / 'index-building6.json', index)
    print('index-building6.json:', len(records), 'parts', flush=True)


if __name__ == '__main__':
    main()
