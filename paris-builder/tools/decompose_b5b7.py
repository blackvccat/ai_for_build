"""Decompose building5/building7 (巴黎建筑素材5/7) corner-chamfer family into library-v4 atlas-techniques.

Same lossless pipeline as tools/decompose_street4.py: source crop, air-padding trim,
explicit chain->iron_chain rename for 1.21.11, create:* modded blocks preserved and
flagged compatible_vanilla=false, roundtrip + load checks, registry validation,
seven-view previews. Output goes to knowledge/library-v4/atlas-techniques/<id>/
plus index-b5b7.json. Idempotent: geometry is rewritten deterministically; previews
are re-rendered only when the detail schematic hash changes.

Measured layout (probes in runs/TECHNIQUE-ATLAS-v0.1/probe_b5_*.txt, probe_crops/b5|b7-*):
- 素材5 (83x44x172, civic palace around a courtyard): both z_max (south, main facade)
  corners are L-shaped recessed corner notches (walls step back, corner void stays
  open to the street, cornice+roof bridge over it). SE corner (x 75-81, z 164-171)
  is the richer one: full-height rusticated corner pier (dirt/mud_bricks/mushroom
  texture), warped-door ground floor pairs on the east facade return, two window
  bays on the south facade end. Giant order pilasters run both upper storeys on the
  east/west facades (fence+button pilaster strips, red-toned capitals y22-26).
- 素材7 (205x63x26, gare-like hall): z_max (south) ornate facade with 7 grand arch
  bays (period 21, 4-wide opening, arch ring projected 2 blocks at z=19-21, dark
  window surface at z=20). Both z_max corners carry small ~4-block chamfers
  (plinth steps + corner pylon + parapet setback). Pavilion crowns at both x ends:
  north stepped dome (peak y62) + clock oculi on both z faces. Hall roof is a solid
  barrel vault with light-stripe and elliptical eye patterns (NOT glazed, NO
  dormers anywhere - both documented as negative findings).
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
SOURCES = {
    'building5': ROOT.parent / '巴黎建筑素材/巴黎建筑素材5.schem',
    'building7': ROOT.parent / '巴黎建筑素材/巴黎建筑素材7.schem',
}
SOURCE_REL = {
    'building5': '巴黎建筑素材/巴黎建筑素材5.schem',
    'building7': '巴黎建筑素材/巴黎建筑素材7.schem',
}
VIEWS = ['front', 'back', 'left', 'right', 'top', 'axonometric_front', 'axonometric_back']
VANILLA_NOTE = '目标版本方块注册表通过；装配与游戏行为尚需验证。'
MODDED_NOTE = '含未转译模组方块：仅保留源证据，排除原版直接装配；预览中的替代模型不算原模型验证。'

PARTS = [
    {
        'id': 'b5-corner-chamfer-base', 'source': 'building5', 'bbox': [67, 0, 158, 83, 10, 172],
        'title': '素材5 · 东南隅切角基座段（凹角小庭+粗凿隅石+诡异木门洞）',
        'families': ['outer_corner', 'quoin', 'rustication', 'window_surround', 'plinth'],
        'outside': 'south/+z（主立面）+ east/+x（东立面尾段）',
        'observation': '市政楼主立面（南/z_max）东南隅的 L 形凹角：南面墙（z=167/168）与东面墙（x=80/81）'
                       '在角部退让，x76-80×z165-171 自地面起全空，形成向街角开放的凹角小庭。'
                       '凹角各面各自成立面：凹角内回头墙（z=164，x76-80）开两拱形雕像龛（黑饰雕像+砂岩拱框），'
                       '粗凿隅石大柱墩（x70-75 六格宽：深板岩基座 y2-8，东棱 x75 以 rooted_dirt 锈石收角，'
                       '柱面垂绿饰板），其西一窄龛开间（x68-69），东面尾段一樘诡异木双联门洞'
                       '（warped_door y1-5 冻结 half=lower 叠置，stripped_warped_hyphae 门框，z159-162，'
                       '北面同制第二樘在 z153-156 裁切外）；南面锈石门脸带 create 方解石墙窗台钉（y6 成对）；'
                       'y8-9 层间带（砂岩/花岗岩墙+stripped_oak_wood+pink_wool 色带）绕两立面并探入凹角边缘；'
                       '全落地 y=0，无地形高差；件内含源有实心填充（白羊毛芯），裁切面所见即填充。',
        'constraint': '凹角是源有的开放小庭，拼接时不得封堵；create:cut_calcite_wall 窗台钉为模组方块'
                      '（2 格，y6），原版装配需替换浅色墙类；warped_door 全为 half=lower 冻结态，禁当可开启门洞；'
                      '西、北裁切面切断长立面与室内填充，连接态冻结入账，粘贴须关方块更新。',
        'finding': None,
    },
    {
        'id': 'b5-corner-chamfer-body', 'source': 'building5', 'bbox': [67, 10, 158, 83, 28, 172],
        'title': '素材5 · 东南隅切角主体段（隅石贯通+回头面开窗+檐口桥接凹角）',
        'families': ['outer_corner', 'quoin', 'window_surround', 'string_course', 'cornice'],
        'outside': 'south/+z（主立面）+ east/+x（东立面尾段）',
        'observation': '切角主体段两层通高（y10-27）：南面东端窗开间（窄龛 x68-69 上窗 + 隅石柱墩 x70-75）'
                       '铁门薄窗（前后两层 half=lower 冻结态）+橡木/桦木栅栏窗台+piston_head 牛腿'
                       '+birch_trapdoor 横档，东面尾段同制窗面向东；'
                       '粗凿隅石柱墩东棱（x75：rooted_dirt/mud_bricks/dirt/brown_mushroom_block 逐层换材的'
                       '锈石肌理 y9-21 + 蜂巢/去皮桦木/骨块/loom 柱头 y22-26）自基座贯通至檐口，是读角的主线；'
                       '凹角（x76-80×z165-171）在主体段保持全空，仅 y21-22 层间带探入缺口边缘；'
                       '檐口（y26-27：stone_brick/andesite/cobblestone 等多种半砖混砌+birch_fence_gate+砂岩墙）'
                       '在凹角上方桥接两立面，角部檐口不断；件内含源有实心填充（白羊毛芯）。',
        'constraint': '凹角上空仅由檐口桥接，墙体不上去——"墙退檐进"是该切角的核心读法；'
                      '隅石柱柱头（蜂巢/loom 等）为冻结装饰态；薄窗面铁门禁当真门洞；'
                      '与 base、crown 上下对位叠合（crown 平面更大，含东面老虎窗），裁切面连接冻结需延续或做端头。',
        'finding': None,
    },
    {
        'id': 'b5-corner-chamfer-crown', 'source': 'building5', 'bbox': [64, 26, 150, 83, 40, 172],
        'title': '素材5 · 东南隅切角顶帽（檐口绕角+曼萨德过凹角+东面老虎窗）',
        'families': ['outer_corner', 'cornice', 'roof_slope', 'dormer', 'ridge'],
        'outside': 'roof（凹角朝东南）',
        'observation': '切角顶帽：混砌半砖檐口带（y26-27）绕角连续，与曼萨德屋面一起在凹角上空桥接——'
                       '凹角小庭被屋顶覆盖但墙身不升，形成"盖顶不退"的收头；'
                       '曼萨德陡坡（深板岩系杂混肌理：tuff/gravel/cobblestone/andesite 等逐层换材 y28-37，'
                       '每 1-2 层内收）在角部作对角转折，脊线向角斜收；'
                       '南面两樘砂岩颊老虎窗（z=165，颊条 x64-67 与 x70-73：铁门暗窗 y28-30 薄窗面'
                       '+白框+蘑菇茎帽顶 y32+链饰 y33，chain→iron_chain）嵌于坡脚；'
                       '檐口链挂边（已改名 iron_chain）。',
        'constraint': '屋脊在角部对角斜收，不可拉平成直线脊；两樘老虎窗与 body 段南面窗开间同轴；'
                      'chain 已显式改名 iron_chain；与 body 在 y26-27 檐口层叠合'
                      '（本件平面 x64/z150 比 base/body 的 x67/z158 大，为含两樘坡脚老虎窗）。',
        'finding': None,
    },
    {
        'id': 'b5-pilaster-giant', 'source': 'building5', 'bbox': [72, 0, 102, 80, 29, 107],
        'title': '素材5 · 东立面贯通巨型壁柱开间（栅栏棱+按钮钉+柱头换材）',
        'families': ['pilaster', 'window_surround', 'string_course', 'cornice', 'rustication'],
        'outside': 'east/+x',
        'observation': '东立面（x_max）标准窗开间的市政类巨型壁柱：壁柱条为砂/砂岩柱芯（x74-76）'
                       '+橡木栅栏外棱（x77）+桦木按钮钉（x78 外侧逐层钉点），自 y10 贯通两层至 y21；'
                       '柱头逐层换材（蜂巢 beehive/去皮桦木/砂岩/骨块/loom，y22-26），'
                       '檐口底挂链饰齿（chain→iron_chain，y21/24）；开间窗为三层薄窗面'
                       '（白玻璃 x74+铁活板 x75+铁门 half=lower 冻结态 x76，y11-14 与 y18-21 两层），'
                       '窗台钉为 create 方解石墙（y6，模组方块）；底层为锈石拱廊（深板岩柱肢+雕像龛）'
                       '与 y8-9 层间带（含 pink_wool 色带），承托上部壁柱。',
        'constraint': '巨型壁柱的两层贯通与柱头换材是市政立面标志，不可压成单层壁柱；'
                      'create 钉 2 格保留入账，原版需替换；铁门薄窗禁当真门；'
                      '开间模数 6（壁柱 3+窗 2+壁柱 1 节奏），复用按整模数错位。',
        'finding': None,
    },
    {
        'id': 'b7-corner-chamfer-west', 'source': 'building7', 'bbox': [0, 0, 12, 52, 34, 26],
        'title': '素材7 · 主立面西南隅小切角（钟楼配楼角部+首拱衔接）',
        'families': ['outer_corner', 'arch', 'portal', 'rustication', 'parapet'],
        'outside': 'south/+z（主立面）+ west/-x（西端面）',
        'observation': '会堂 z_max 主立面西端转角：钟楼配楼（x1-30）西南外角作约 4 格小切角——'
                       '角部以阶梯退让表达：勒脚台阶（x3-8、z24-25，y0-8）、角柱墩（x4-7、z22-23，'
                       '至女儿墙）、女儿墙角部（y33）逐层收分；切角区立面自立：配楼面开双扇高木门'
                       '（深色橡木门 y0-8）+ 上方拱券小窗（蓝白玻璃 y10-16，与主拱同法）'
                       '+拱形壁龛勋章饰面（x20-26）+锈石分缝；东面衔接第一个大拱开间（x31-51），'
                       '主立面"墙身 z=17/18 → 拱环前挑 z=19-21 → 暗窗面 z=20"的三层纵深做法'
                       '在角部与开间交界处完整可读。',
        'constraint': '切角是 2-4 格级的小尺度角部退让，复用时保持勒脚台阶与角柱墩的阶梯关系；'
                      '钟面在 y34 以上被裁（完整钟与穹顶见 b7-pavilion-crown）；'
                      '北裁切面（z=12）切断配楼，连接态冻结入账。',
        'finding': None,
    },
    {
        'id': 'b7-arch-window', 'source': 'building7', 'bbox': [44, 0, 14, 70, 34, 26],
        'title': '素材7 · 主立面拱券长窗开间（半圆拱体素逼近+三层纵深）',
        'families': ['arch', 'window_surround', 'mullion', 'sill', 'pilaster'],
        'outside': 'south/+z',
        'observation': '会堂主立面标准拱券开间（模数 21：17 格间壁+4 格窗洞）：半圆拱以整方块与楼梯'
                       '在墙面前逐层放级逼近——拱环自洞口（x48-51）两侧 y16 起弧，z=19 前挑 1 格、'
                       '拱带 z=19-21，至 y22 拱肩合拢（环宽自 45-54 放到 42-57 再收回）；'
                       '暗窗面（深灰竖梃+灰蓝玻璃横档多层，z=20）比拱环退 1 格、比墙身（z=17/18）'
                       '前挑 2 格，形成"墙—拱环—窗面"三层纵深；窗下白色窗台（雪片/白地毯 y7-8），'
                       '底层深色大门（铁栏与深色门 y0-6）；右侧 17 格间壁以隔层竖槽分缝'
                       '（z=18 交替开洞）并带勋章饰面，拱顶上方栏板女儿墙与金饰冠（y24-33）对中间壁。',
        'constraint': '拱的读法靠"z 向前挑+逐层放级"而非楼梯斜面拼弧，复用时保持三层 z 纵深；'
                      '间壁竖槽是隔层冻结开洞，勿填平；两端裁切穿过相邻开间，栏板冠饰顶部在 y34 裁断。',
        'finding': None,
    },
    {
        'id': 'b7-pavilion-crown', 'source': 'building7', 'bbox': [0, 30, 0, 31, 63, 26],
        'title': '素材7 · 西端钟楼顶帽（双面钟+阶梯穹顶+雉堞鼓座）',
        'families': ['roof_ornament', 'finial', 'parapet', 'roof_slope', 'arch'],
        'outside': 'roof（钟面朝 south/+z 与 north/-z）',
        'observation': '西端钟楼完整顶帽：南面圆形钟（深色钟盘+红/白刻度指针，蓝白光圈+砂岩花环框，'
                       'y33-40，框缘以枯珊瑚扇/雪花小件密饰）架于主立面之上；'
                       '北侧带钟八角阶梯穹顶（深板岩整方块阶梯收分 y40-57，每隔数层嵌棕色横带，'
                       '尖顶饰柱至 y62）立于灰色雉堞鼓座（y33-39，栏板柱+齿饰）之上；'
                       '穹顶底部另有一圈拱廊式小券环（y36-39）。',
        'constraint': '穹顶是整方块阶梯收分而非楼梯坡，收分节奏不可改；钟面小件（珊瑚扇/雪花）'
                      '为禁更新冻结态；底部 y=30 裁在配楼墙身上，与 b7-corner-chamfer-west 上下对位。',
        'finding': None,
    },
    {
        'id': 'b7-roof-vault-eye', 'source': 'building7', 'bbox': [92, 24, 8, 118, 38, 26],
        'title': '素材7 · 大厅筒拱屋面横段（实心灰白条纹+椭圆光眼+高侧窗带）',
        'families': ['roof_slope', 'arch', 'parapet', 'roof_ornament', 'window_surround'],
        'outside': 'roof（高侧窗带朝 south/+z）',
        'observation': '大厅筒拱横段（x92-117）：拱顶曲面以深板岩/闪长岩/安山岩半砖混砌（y26-28），'
                       '灰白浅材纵向条纹与椭圆"光眼"图案沿 x 每隔约 15 格一组——实测为实心砌筑的'
                       '装饰图案，非玻璃天窗（否定情报）；南侧高侧窗带（z19-21：砂岩墙基 y24'
                       '+cut_sandstone 壁 y25-31+橙框小窗+橡木活板檐 y32）给大厅采光，'
                       '带上栏板女儿墙与金饰奖杯冠（z22-24，至 y33）；北缘 z=8 裁在拱顶曲面上。',
        'constraint': '筒拱是实心装饰拱，光眼为浅材图案而非洞口，不可当透明天窗处理；'
                      '高侧窗带才是真实采光口；x 向两端各带半组图案，复用按约 15 格模数延展。',
        'finding': None,
    },
]


FINDINGS = {
    'b5-corner-chamfer-base': '七视角确认：凹角内回头墙两拱形雕像龛、隅石大柱墩（绿饰板+锈石收角）、'
                              '西面窄龛开间、东面诡异木双联门洞一对、create 窗台钉与 y8-9 层间带绕角齐全；'
                              '凹角小庭自地面全空、向街角开放，件内白羊毛实心填充为源有做法，均已注明。',
    'b5-corner-chamfer-body': '七视角确认：隅石柱墩东棱（rooted_dirt/mud_bricks/dirt/蘑菇块锈石肌理）两层贯通至柱头、'
                              '两回头面窗开间完整、凹角主体段全空而 y26-27 檐口在其上桥接两立面，'
                              '"墙退檐进"读法成立；室内羊毛填充在裁切面可见，已注明。',
    'b5-corner-chamfer-crown': '七视角确认：檐口绕角连续、曼萨德角部对角转折与脊线斜收、南面两樘砂岩颊老虎窗'
                               '（铁门暗窗+白框+蘑菇茎帽+链饰）完整、凹角上空被屋面覆盖；'
                               'top 视角可见角部檐口 L 形绕合与屋脊走向。',
    'b5-pilaster-giant': '七视角确认：壁柱条（栅栏棱+按钮钉）两层贯通、柱头逐层换材、链饰齿、'
                         '三层薄窗面与底层锈石拱廊完整；create 窗台钉 2 格已标注。',
    'b7-corner-chamfer-west': '七视角确认：西南角勒脚台阶、角柱墩与女儿墙的小切角阶梯、配楼高木门与拱券小窗、'
                              '壁龛勋章饰面齐全；东面第一个大拱开间完整入件，切角与主拱衔接关系可读；'
                              '顶部钟面裁断已在约束注明。',
    'b7-arch-window': '七视角确认：半圆拱环 z 向前挑逐层放级、暗窗面三层纵深、白色窗台、底层大门、'
                      '间壁竖槽分缝与勋章饰面、栏板女儿墙与金饰冠完整；左缘带相邻开间边缘作模数参照。',
    'b7-pavilion-crown': '七视角确认：南面钟（钟盘/刻度/蓝白光圈/花环框）完整、八角阶梯穹顶与棕色横带、'
                         '尖顶饰柱、雉堞鼓座与底部小券环齐全；北、东、西三面裁切为屋面延续。',
    'b7-roof-vault-eye': '七视角确认：筒拱曲面半砖混砌、灰白条纹与两组椭圆光眼（实心图案）、'
                         '南侧高侧窗带（橙框小窗+活板檐）与栏板奖杯冠完整；top 视角可见光眼非洞口。',
}


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
    sid = part['source']
    record = {
        'id': part['id'], 'title': part['title'], 'bbox': part['bbox'],
        'source': SOURCE_REL[sid], 'source_id': sid, 'source_sha256': source_sha,
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
        'claim_status': 'SOURCE_STATES_VERIFIED_SEMANTICS_ANNOTATED',
        'role_review': 'PENDING_VISUAL_REVIEW',
        'compatible_vanilla': vanilla,
        'compatibility_note': VANILLA_NOTE if vanilla else MODDED_NOTE,
        'entity_scope': 'block geometry only; source NBT in source-nbt-context.json',
    }
    if part.get('finding') or FINDINGS.get(part['id']):
        record['role_review'] = {'reviewer': 'agent visual inspection', 'reviewer_type': 'agent',
                                 'decision': 'ANNOTATED_REFERENCE',
                                 'finding': part.get('finding') or FINDINGS[part['id']],
                                 'game_acceptance': 'NOT_RUN'}
        record['claim_status'] = 'SOURCE_STATES_VERIFIED_VISUALLY_INTERPRETED'
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
    data = {sid: load_schematic(path) for sid, path in SOURCES.items()}
    source_meta = {}
    for sid, path in SOURCES.items():
        d = data[sid]
        meta = {'id': sid, 'path': SOURCE_REL[sid], 'name': path.name, 'sha256': digest(path),
                'data_version': d.data_version, 'dimensions_whd': [d.width, d.height, d.length],
                'nonair': int(d.nonair_mask().sum()), 'air_palette_ids': d.air_ids.tolist()}
        if sid == 'building5':
            meta['layout_note'] = ('环形院落市政楼（酒店/市政厅类）：z_max 南立面为主立面（中央塔楼+钟、'
                                   '贯通巨型壁柱、锈石拱廊基座、曼萨德+老虎窗），东南/西南两隅为 L 形凹角切角'
                                   '（墙退檐进）；create:cut_calcite_wall 仅 104 格（基座窗台钉）。')
        else:
            meta['layout_note'] = ('会堂/车站类长厅（205 长）：z_max 南立面为主立面（7 大拱券开间+两端钟楼配楼'
                                   '+双面钟+阶梯穹顶），z_min 北立面为次立面（矩形长窗）；两前角小切角约 4 格；'
                                   '大厅为实心筒拱顶（灰白条纹+椭圆光眼图案），无玻璃天窗、无老虎窗。')
        source_meta[sid] = meta
    OUT.mkdir(parents=True, exist_ok=True)
    records = []
    for part in PARTS:
        if args.only and part['id'] not in args.only:
            saved = OUT / part['id'] / 'record.json'
            if saved.exists():
                records.append(json.loads(saved.read_text(encoding='utf-8')))
            continue
        record = build_part(data[part['source']], part, catalog, source_meta[part['source']]['sha256'], args.render)
        records.append(record)
        print(part['id'], record['inventory']['dimensions_whd'], record['inventory']['nonair'],
              record['validation']['registry_status'], 'migrations', len(record['cleaning']['version_migrations']),
              flush=True)
    index = {'schema': 'atlas-techniques-v4-b5b7',
             'coordinate_convention': 'source-local xyz; bbox [x0,y0,z0,x1,y1,z1], upper bounds exclusive',
             'sources': list(source_meta.values()),
             'cleaning_policy': 'PRESERVE_SOURCE_WITH_EXPLICIT_TARGET_VERSION_RENAMES',
             'update_policy': 'PASTE_WITH_BLOCK_UPDATES_DISABLED',
             'game_acceptance': 'NOT_RUN',
             'negative_findings': [
                 {'id': 'b7-dormer', 'topic': '素材7 老虎窗',
                  'finding': '实测全屋顶（top-y 逐格扫描）：大厅为实心筒拱顶、两端为阶梯穹顶，'
                             '源内不存在任何老虎窗；情报“屋顶有老虎窗迹象”不成立，故无老虎窗裁件。'},
                 {'id': 'b7-skylight-glazed', 'topic': '素材7 玻璃天窗',
                  'finding': '筒拱顶的灰白条纹与椭圆“光眼”逐格核验为 polished_deepslate/diorite/andesite '
                             '半砖实心砌筑的装饰图案，不存在玻璃天窗；真实采光口为南侧高侧窗带'
                             '（见 b7-roof-vault-eye）。'},
                 {'id': 'b5-corner-choice', 'topic': '素材5 切角定位',
                  'finding': '情报坐标 (0,171) 指西南隅；实测东南（退让 5×4）与西南（退让 3×4）两隅为同型 '
                             'L 形凹角（墙退檐进、凹角小庭开放），取构造更完整的东南隅入件，'
                             '西南隅不重复裁。'},
             ],
             'parts': [{'id': r['id'], 'title': r['title'], 'source': r['source_id'],
                        'bbox': r['source_bbox_xyz_half_open'],
                        'dimensions_whd': r['inventory']['dimensions_whd'], 'nonair': r['inventory']['nonair'],
                        'families': r['families'], 'outside': r['outside'],
                        'compatible_vanilla': r['compatible_vanilla'],
                        'schematic': r['schematic'], 'record': relative(OUT / r['id'] / 'record.json')}
                       for r in records]}
    dump_json(OUT / 'index-b5b7.json', index)
    print('index-b5b7.json:', len(records), 'parts', flush=True)


if __name__ == '__main__':
    main()
