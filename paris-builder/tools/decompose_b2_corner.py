"""Decompose building2 corner elements (arc corner, dome, roof cresting) into library-v4.

Same lossless pipeline as tools/decompose_reference_sources.py (v3): source crop,
air-padding trim, explicit chain->iron_chain rename for 1.21.11, roundtrip checks,
registry validation, seven-view previews. Output goes to
knowledge/library-v4/atlas-techniques/<id>/ plus index-building2-corner.json.
Idempotent: geometry is rewritten deterministically; previews are re-rendered only
when the detail schematic hash changes.
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
SOURCE_REL = '巴黎建筑素材/巴黎建筑素材2.schem'
SOURCE = ROOT.parent / '巴黎建筑素材/巴黎建筑素材2.schem'
OUTSIDE = 'west/-x + south/+z'
VIEWS = ['front', 'back', 'left', 'right', 'top', 'axonometric_front', 'axonometric_back']

PARTS = [
    {
        'id': 'b2-corner-base',
        'bbox': [2, 0, 78, 22, 13, 96],
        'title': '素材2 · 圆弧转角基座段',
        'families': ['diagonal_corner', 'shopfront', 'plinth'],
        'observation': '转角基座是绕弧橱窗带：西翼橱窗用雪层板 snow[layers=7] 做半透窗面、链条竖梃、青色玻璃点缀；'
                       '弧面橱窗自 z=87 起按 1、2、2、1 格阶梯绕角（青色玻璃对角带 + 链条梃），与主体层的对角窗带同一逼近法；'
                       '南翼恢复雪板+青玻璃成组橱窗。石材为石英/闪长岩白色基座，转角开间（z 78-86）比两翼标准开间更宽。',
        'constraint': '弧面两侧为裁切面；与两翼基座按同一街道立面线拼接，裁断的墙/玻璃连接需在拼接时延续。',
    },
    {
        'id': 'b2-corner-body-1',
        'bbox': [2, 19, 78, 22, 31, 96],
        'title': '素材2 · 圆弧转角主体开间（二、三层）',
        'families': ['diagonal_corner', 'window_surround', 'mullion', 'sill'],
        'observation': '圆弧用 45° 对角玻璃带逼近：转角窗自 z=86 起每向南 1 格向 +x 错 0-1 格，'
                       '宽度按 1、2、3、4 格阶梯展开，连成绕弧斜向窗带；两翼为 2 格宽成组窗（间距 3/6 格），'
                       '墙面随带阶梯进退，每步 1 格。',
        'constraint': '两层叠置的完整转角开间；东西两侧为裁切面，栏杆与墙面连接冻结在边界，拼接时需延续或做端头。',
    },
    {
        'id': 'b2-corner-body-2',
        'bbox': [2, 31, 78, 22, 39, 96],
        'title': '素材2 · 圆弧转角顶层与绕弧阳台',
        'families': ['diagonal_corner', 'balcony_slab', 'balustrade', 'cornice'],
        'observation': '顶层墙面向内退 2 格（x 5→7），让出绕弧连续阳台：阳台板与砂岩墙栏杆沿同一 45° 阶梯绕转角包裹，'
                       '对角玻璃带位置不变；其上接多道檐口线脚（y 36-38），檐板向外挑 1-2 格。',
        'constraint': '阳台栏杆的 low/tall 连接在裁切边界冻结；与 body-1 上下叠合时墙线退台关系必须保持。',
    },
    {
        'id': 'b2-corner-crown-drum',
        'bbox': [0, 38, 37, 19, 47, 59],
        'title': '素材2 · 穹顶鼓座与檐口基盘',
        'families': ['cornice', 'pediment', 'roof_ornament'],
        'observation': '鼓座立在通长檐口平板（y 38）上：正面突出 2 格（至 x=1），中央开拱形长窗'
                       '（砂岩拱圈 + 拱心石，黑色玻璃填面），两侧壁龛以桦木门叶（全部 half=lower，源冻结态）'
                       '做薄饰面板，外缘一对涡卷扶壁自鼓座升起、向上接入穹顶起拱圈；扶壁外为两翼曼萨德屋面与氧化铜檐边。',
        'constraint': '檐口平板在 x/z 向均为通长构件的裁切段；鼓座是穹顶的承重基盘，须与 crown-dome 上下对位；'
                      '涡卷扶壁在 y=46 处切断，延续部分在 crown-dome。',
    },
    {
        'id': 'b2-corner-crown-dome',
        'bbox': [0, 47, 37, 19, 61, 59],
        'title': '素材2 · 穹顶本体与顶部尖饰',
        'families': ['roof_ornament', 'finial', 'roof_slope'],
        'observation': '穹顶是 1-2 格厚的空心壳：氧化铜皮外壳自 y 47 起每 1-2 层向内收 1 格'
                       '（z 38/57→42/53、x 6/7→10/11），壳腔衬深板岩/凝灰岩，y 58 合拢为顶板；'
                       '顶板一周以 dark_oak_fence 柱、砂岩墙栏杆（up=false）与凋零玫瑰做尖饰脊线（y 59-60），'
                       '壳体正面开两扇铜框小窗，背后接后部高体量屋面。',
        'constraint': '穹顶背面与后部体量相接处为裁切面（z=58 后壁切断）；底部 y 47 起拱圈在背面不闭合（源建筑即如此），'
                      '与 crown-drum 上下叠合使用。',
    },
    {
        'id': 'b2-roof-cresting',
        'bbox': [16, 48, 83, 23, 58, 92],
        'title': '素材2 · 屋脊烟囱亭帽（转角段）',
        'families': ['chimney_cap', 'finial', 'ridge'],
        'observation': '立在曼萨德屋脊上的装饰烟囱亭：砂岩墙以 low/tall 单向肢做通透栏身（up=false），'
                       '氧化铜皮收顶，四面贴珊瑚扇与木栅栏门做浮雕装饰，底部与深板岩坡面咬合。',
        'constraint': '亭帽整件裁自屋脊，含根部坡面咬合段；底部坡面在四周为裁切面。',
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
    raw_read = load_schematic(folder / 'source-crop.schem')
    source_equal = bool(np.array_equal(np.asarray(raw_read.id_to_state, dtype=object)[raw_read.volume], raw))
    if not source_equal or not transformed_equal:
        raise ValueError('Export changed source states: ' + part['id'])
    dump_json(folder / 'source-nbt-context.json', context_entities(data, part['bbox']))
    registry = folder / 'registry.json'
    result = subprocess.run([node_binary(), str(ROOT / 'tools/validate_schematic.cjs'),
                             str(folder / 'detail.schem'), str(registry)], capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=120)
    check = json.loads(registry.read_text(encoding='utf-8')) if registry.exists() else {'status': 'FAIL', 'issues': [result.stderr]}
    inv = inventory(cleaned)
    record = {**part, 'source_id': 'building2', 'source': SOURCE_REL, 'source_sha256': source_sha,
              'outside': OUTSIDE, 'source_bbox_xyz_half_open': part['bbox'],
              'clean_origin_source_xyz': offset, 'inventory': inv, 'source_inventory': original_inventory,
              'cleaning': cleaning, 'state_context': state_context(data, cleaned, offset),
              'library_matches': family_matches(part['families'], inv['exact_states'], catalog),
              'schematic': relative(folder / 'detail.schem'), 'schematic_sha256': digest(folder / 'detail.schem'),
              'raw_schematic': relative(folder / 'source-crop.schem'),
              'parent': 'building2',
              'validation': {'source_states_equal': source_equal, 'documented_transform_equal': transformed_equal,
                             'registry_status': check['status'], 'registry_issues': check.get('issues', []),
                             'game_acceptance': 'NOT_RUN'},
              'claim_status': 'SOURCE_STATES_VERIFIED_SEMANTICS_ANNOTATED',
              'role_review': 'PENDING_VISUAL_REVIEW',
              'compatible_vanilla': check['status'] == 'PASS',
              'compatibility_note': '目标版本方块注册表通过；装配与游戏行为尚需验证。' if check['status'] == 'PASS'
                                    else '含未转译模组方块：仅保留源证据，排除原版直接装配；预览中的替代模型不算原模型验证。',
              'entity_scope': 'block geometry only; source NBT in source-nbt-context.json'}
    dump_json(folder / 'record.json', record)
    if render:
        cache_path = folder / 'previews/render_cache.json'
        cached = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.exists() else {}
        if cached.get('schematic_sha256') != record['schematic_sha256']:
            render_previews(folder / 'detail.schem', folder / 'previews', max_size=700)
            dump_json(cache_path, {'schematic_sha256': record['schematic_sha256'], 'views': VIEWS})
    return record


REVIEWS = {
    'b2-corner-base': '七视角确认单元完整：西翼加宽橱窗开间、弧面青色玻璃对角带与链条竖梃、南翼首个完整开间均在件内；'
                      '雪层板 snow[layers=7] 窗面与 v3 b2-base 的玻璃做法不同，是独立的基座橱窗样本。',
    'b2-corner-body-1': '七视角确认单元完整：两层叠置转角开间，45° 对角玻璃带按 1/2/3/4 格阶梯绕弧（top 视角最清晰），'
                        '与两翼 2 格成组窗的开间关系保留；裁切边界的栏杆与墙连接已在 state_context 入账。',
    'b2-corner-body-2': '七视角确认单元完整：顶层墙线退 2 格、绕弧连续阳台（板+链条栏杆）与多道檐口均在件内，'
                        'top 视角可见檐口镶板沿 45° 对角排布；与 body-1 的上下叠合关系成立。',
    'b2-corner-crown-drum': '七视角确认单元完整：鼓座正面拱形长窗、两侧壁龛、涡卷扶壁起点与檐口基盘均在件内；'
                            '扶壁在 y=46 的切断为有意分段，延续部分在 crown-dome。',
    'b2-corner-crown-dome': '七视角确认单元完整：氧化铜壳体逐层收分、空心壳腔（front/back 剖面可见 1-2 格壳厚与填充）、'
                            'y 58 顶板与栅栏柱+凋零玫瑰尖饰脊线均在件内；南烟囱亭已排除出包围盒（z1=59）。',
    'b2-roof-cresting': '七视角确认单元完整：烟囱亭帽四面珊瑚扇浮雕带、砂岩墙 C 形栏（up=false+low/tall 单向肢）、'
                        '铜皮收顶与根部深板岩坡面/铜脊咬合关系均保留。',
}


def apply_reviews(records):
    for r in records:
        finding = REVIEWS.get(r['id'])
        folder = OUT / r['id']
        if not finding or not all((folder / 'previews' / (v + '.png')).exists() for v in VIEWS):
            continue
        r['role_review'] = {'reviewer': 'Kimi Code visual inspection', 'reviewer_type': 'agent',
                            'decision': 'ANNOTATED_REFERENCE', 'finding': finding,
                            'evidence': relative(folder / 'previews'), 'game_acceptance': 'NOT_RUN'}
        r['claim_status'] = 'SOURCE_STATES_VERIFIED_VISUALLY_INTERPRETED'
        dump_json(folder / 'record.json', r)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--render', action='store_true')
    parser.add_argument('--only', nargs='*')
    args = parser.parse_args()
    catalog = json.loads((ROOT / 'knowledge/library-v1/catalog.json').read_text(encoding='utf-8'))
    data = load_schematic(SOURCE)
    source_sha = digest(SOURCE)
    source_meta = {'id': 'building2', 'path': SOURCE_REL, 'name': SOURCE.name, 'sha256': source_sha,
                   'nonair': int(data.nonair_mask().sum()), 'fill_ratio': float(data.nonair_mask().mean()),
                   'air_palette_ids': data.air_ids.tolist(), 'offset_xyz': list(data.offset),
                   'dimensions_whd': [data.width, data.height, data.length], 'outside': OUTSIDE,
                   'corner_note': '转角实测：-x 与 +z 为街面，+x 中部为盲共墙；x_min 端两侧各有一处 45°/圆弧切角（进深约 12 格）；'
                                  '本批裁件取自西南转角（x_min,z_max）与西立面中央穹顶。'}
    OUT.mkdir(parents=True, exist_ok=True)
    records = []
    for part in PARTS:
        if args.only and part['id'] not in args.only:
            saved = OUT / part['id'] / 'record.json'
            if saved.exists():
                records.append(json.loads(saved.read_text(encoding='utf-8')))
            continue
        record = build_part(data, part, catalog, source_sha, args.render)
        records.append(record)
        print(part['id'], record['inventory']['dimensions_whd'], record['inventory']['nonair'],
              record['validation']['registry_status'], flush=True)
    apply_reviews(records)
    validation = {
        'source_files_unchanged': digest(SOURCE) == source_sha,
        'parts': len(records),
        'source_state_roundtrips': sum(r['validation']['source_states_equal'] for r in records),
        'registry_pass': sum(r['validation']['registry_status'] == 'PASS' for r in records),
        'visually_reviewed_parts': sum(isinstance(r['role_review'], dict) for r in records),
        'changed_nonair_cells': sum(r['cleaning']['changed_nonair_cells'] for r in records),
        'technique_families': sorted({f for r in records for f in r['families']}),
        'game_acceptance': 'NOT_RUN',
        'scope': 'building2 corner arc, dome and roof cresting; complements library-v3 b2-* front pieces'}
    index = {'schema': 'library-v4/atlas-techniques/building2-corner-v1',
             'basis': 'same lossless pipeline as library-v3/reference-techniques; corner-specific supplement',
             'sources': [source_meta], 'parts': records, 'validation': validation}
    dump_json(OUT / 'index-building2-corner.json', index)
    print(json.dumps(validation, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
