"""Evidence-backed, layered knowledge and local semantic search.

SQLite stores complete records AND float32 vectors in one transaction. Embeddings
are a rebuildable index; an embedding never promotes a candidate to good design.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import threading

import numpy as np

from .retrieval import SemanticEncoder, MODEL_ID, MODEL_REVISION, component_record
from .schematic import load_schematic

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / 'knowledge/learning/knowledge.sqlite3'
LAYERS = {'structure': '建筑结构', 'facade': '立面风格', 'technique': '建造技法', 'component': '实体构件'}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def evidence(path, locator='', **extra):
    path = Path(path).resolve()
    return {'path': path.relative_to(ROOT.parent).as_posix(), 'sha256': digest(path),
            'locator': locator, **extra}


def record(ident, layer, title, summary, refs, **kwargs):
    return {'id': ident, 'layer': layer, 'title': title, 'summary': summary,
            'origin': 'existing_rule', 'claim_status': 'INFERRED', 'game_status': 'NOT_RUN',
            'quality': 'unreviewed', 'dimensions': None, 'image': None, 'schematic': None,
            'sources': [], 'constraints': [], 'observations': [], 'inferences': [],
            'evidence': refs, 'links': [], **kwargs}


FORMS = {
    'street_house': ('窄地块联排住宅', '临街窄面宽、较深进深，两侧共用隔户墙。适合狭窄宅基地；共墙不能当临街面开窗。'),
    'street_row': ('连续街墙与多户联排', '由多个相邻宅基地组成连续街道，各户保留楼层与屋顶差异。适合一整排巴黎民居街区。'),
    'apartment_block': ('独立公寓与采光天井', '四个可见方向的公寓体量，可设置内部采光天井。侧面和院落需要设计。'),
    'court_palace': ('前院与两翼府邸', '后部主体配合两侧翼楼、前院和入口边界。用于有仪式性入口的府邸空间。'),
    'civic_hall': ('中央亭与两端公共建筑', '长正面由中央高亭与两端体量形成主次。用于公共建筑与纪念性轴线。'),
    'slope_terrace': ('顺坡分段退台街屋', '各段随地形下落，分别管理楼层标高和屋顶。适合有高差的沿街建筑。'),
}
FACADES = {
    'haussmann_apartment': ('奥斯曼公寓立面', '墩窗交替的开间节奏、底层店面、楼层线和重点阳台层。立面保持基座、主体和屋顶层级。'),
    'palace_front': ('府邸主立面', '突出中央入口和冠饰，以高窗、门廊和主次轴线表达府邸的仪式感。'),
    'civic_colonnade': ('公共建筑柱式立面', '粗石基座、巨柱式与拱形底层开口组织公共建筑长正面。'),
    'plain_terrace': ('克制的普通街屋立面', '等距窗组和低装饰密度，用于普通住宅及次要街段。'),
    'shop_terrace': ('连续店铺立面', '底层连续橱窗和招牌带，上部住宅窗组保持秩序。'),
}
RULES = {
    'H-I01': ('基座、主体、檐口与屋顶', '先建立基座、居住主体、檐口和屋顶轮廓的层级。'),
    'H-I02': ('街墙与邻栋檐口协调', '主街立面需要与相邻建筑的高度和檐口关系协调。'),
    'H-I03': ('稳定开间与重点层次', '使用稳定的开间网格，把重点集中在入口、部分阳台楼层、檐口和屋顶变化。'),
    'H-I04': ('街面、院面与转角协同', '主立面、侧面、院落和屋顶共同形成完整体量。'),
}

# Search vocabulary explains the existing family names; it does not promote source
# crops to verified semantics or alter geometry/evidence. Kept separate from scores.
FAMILY_MEANINGS = {
    'downpipe': '雨水从屋顶沿墙排下来的竖向落水管，排水管，雨水管，rainwater downspout',
    'gutter': '沿屋檐收集雨水并导入落水管的横向天沟、檐沟，roof rain gutter',
    'mullion': '窗框内部把玻璃开口分隔成多个小格的竖向窗棂、中梃，window vertical divider',
    'portal': '围绕建筑入口大门的门廊、门口、门洞框架，entrance portal doorway',
    'awning': '入口或店面外遮阳遮雨的棚子、雨棚，canopy awning',
    'dormer': '从坡屋面凸出来带窗的小体量，老虎窗、屋顶窗，roof dormer',
    'chimney': '穿过屋顶排烟的烟囱、烟道，chimney flue',
    'cornice': '墙体顶部向外挑出的檐口收边，用阴影结束立面，cornice',
    'string_course': '楼层之间横向连续的腰线、层间带，horizontal storey band',
    'pilaster': '贴在墙面的浅壁柱，以竖向线条组织开间，pilaster',
    'quoins': '建筑墙角交错布置的隅石、转角石，corner quoins',
    'balcony_slab': '伸出立面的阳台承托板和边缘，balcony platform',
    'railing': '阳台、楼梯或窗前防坠落的栏杆、护栏，balustrade railing',
    'window_surround': '围绕窗洞的窗套、窗楣与窗台框饰，window frame surround',
    'shopfront': '临街商店底层的展示橱窗、店门与招牌带，shopfront storefront',
}


def collect_records():
    catalog_path = ROOT / 'knowledge/library-v1/catalog.json'
    details_path = ROOT / 'knowledge/library-v2/details/index.json'
    catalog, detail_data = read_json(catalog_path), read_json(details_path)
    records, sources, audit = [], {}, {'issues': [], 'inputs': []}
    for path in [catalog_path, details_path, ROOT / 'manifests/source_manifest.json']:
        audit['inputs'].append(evidence(path))

    def add_source(path, image=None, group='源素材', measurements=None):
        path = path.resolve()
        if not path.is_file():
            audit['issues'].append({'kind': 'missing_source', 'path': str(path)})
            return None
        relative = path.relative_to(ROOT.parent).as_posix()
        sid = 'source-' + hashlib.sha256(relative.encode()).hexdigest()[:16]
        if sid not in sources:
            sources[sid] = {'id': sid, 'name': path.stem, 'group': group,
                            'path': relative, 'sha256': digest(path),
                            'image': image, 'measurements': measurements, 'count': 0}
        return sid

    manifest = read_json(ROOT / 'manifests/source_manifest.json')
    for entry in manifest['entries']:
        s = entry['source']
        add_source(ROOT.parent / s['schem']['path'], s['png']['path'], '14 组建筑参考',
                   {'dimensions': entry['schematic']['dimensions'],
                    'nonair_blocks': entry['schematic']['nonair_blocks']})

    for entry in catalog['windows'] + catalog['recipes']:
        old = component_record(entry, catalog['families'])
        ident = 'v1:' + old['id']
        is_source = entry in catalog['windows']
        source_ids = []
        for rel in ([entry['source_schematic']] if is_source else
                    sorted({e['source'] for e in entry.get('evidence', [])})):
            sid = add_source(ROOT.parent / rel, group='源窗' if rel.startswith('窗/') else '14 组建筑参考')
            if sid: source_ids.append(sid)
        directory = ROOT / Path(entry['card']).parent.parent
        schems = sorted(directory.glob('*.schem'))
        schem = schems[0] if schems else None
        family_label = catalog['families'].get(old['family'], '完整窗构件')
        summary = entry.get('visual_interpretation') or f'{family_label}的既有生成配方，第 {entry.get("variant", 0) + 1} 个变体；为组合推导，需试装和视觉复核。'
        refs = [evidence(catalog_path, old['id'])]
        if schem: refs.append(evidence(schem, '完整裁件'))
        records.append(record(ident, 'component', family_label + ' · ' + old['id'], summary, refs,
            family=old['family'], origin='source_crop' if is_source else 'derived_recipe',
            dimensions=[old['width'], old['height'], old['depth']],
            image='paris-builder/' + entry['card'],
            schematic=schem.relative_to(ROOT.parent).as_posix() if schem else None,
            sources=source_ids, constraints=[old['update_policy'], '游戏内状态与审美尚未验收'],
            observations=['已保留精确方块状态与来源记录'],
            inferences=[summary], raw=entry, states=old['states'],
            compatible_vanilla=all(x.startswith('minecraft:') for x in old['states'])))

    # Read exported cuts: compare actual shape/state inventory; no reliance on old report totals.
    hashes = defaultdict(list)
    legacy_audit_path = ROOT / 'knowledge/library-v3/reference-techniques/legacy_audit.json'
    legacy_issues = read_json(legacy_audit_path).get('records', {}) if legacy_audit_path.exists() else {}
    for entry in detail_data['details']:
        ident = 'v2:' + entry['detail_id']
        schem = ROOT / 'knowledge/library-v2/details' / entry['detail_id'] / 'detail.schem'
        source = ROOT.parent / '_incoming_schematics' / entry['source_group'] / entry['source']
        sid = add_source(source, group='补充素材 / ' + entry['source_group'])
        if sid and sources[sid]['sha256'] != entry['source_sha256']:
            audit['issues'].append({'kind': 'source_hash_mismatch', 'id': ident})
        data = load_schematic(schem)
        content_hash = data.voxel_state_hash()
        hashes[content_hash].append(ident)
        actual = Counter(data.id_to_state[int(i)] for i in data.volume.ravel()
                         if data.id_to_state[int(i)] not in ('minecraft:air', 'minecraft:cave_air', 'minecraft:void_air'))
        dimensions = [data.width, data.height, data.length]
        if dict(actual) != entry['exact_block_states'] or dimensions != entry['size_whd']:
            audit['issues'].append({'kind': 'cut_metadata_mismatch', 'id': ident})
        name = '窗部候选' if entry['kind'] == 'window' else '檐口候选'
        cats = entry['frozen'].get('state_categories', {})
        vocabulary = {'wall_connections': '墙肢连接', 'door': '门叶', 'trapdoor': '活板门',
                      'stair_shape': '楼梯形状', 'slab': '半砖', 'railing_connections': '铁栏连接',
                      'pane_connections': '玻璃板连接'}
        methods = '、'.join(vocabulary[k] for k, n in cats.items() if n and k in vocabulary)
        summary = f'从{source.stem}提取的{name}，尺寸 {dimensions[0]}×{dimensions[1]}×{dimensions[2]} 格。包含{methods or "方块状态组合"}；建筑角色和室外朝向待逐件复核。'
        records.append(record(ident, 'component', source.stem + ' · ' + name + ' ' + entry['detail_id'].split('-')[-1],
            summary, [evidence(details_path, entry['detail_id']), evidence(schem, '清洗后裁件')],
            family=entry['kind'], origin='source_crop', dimensions=dimensions,
            schematic=schem.relative_to(ROOT.parent).as_posix(), sources=[sid] if sid else [],
            content_hash=content_hash, raw=entry, states=list(actual),
            compatible_vanilla=all(x.startswith('minecraft:') for x in actual),
            observations=[f'回读 {sum(actual.values())} 个非空气方块，{len(actual)} 种状态',
                          '原索引的冻结状态检查仅是静态检查，不等于游戏内验证'],
            constraints=['粘贴需禁止方块更新', '裁剪完整性、外侧朝向与装配关系仍需复核',
                         '门状态清洗有原始记录；清洗合理性仍需对照源作品'],
            inferences=[f'自动锚点算法分类为 {entry["kind"]}，不能据此判为优秀构件']))
        if ident in legacy_issues:
            records[-1]['retrieval_eligible'] = False
            records[-1]['constraints'] += legacy_issues[ident]
            records[-1]['claim_status'] = 'LEGACY_CROP_REQUIRES_REEXTRACTION'
            records[-1]['evidence'].append(evidence(legacy_audit_path, ident))

    decomposition_path = ROOT / 'knowledge/library-v3/reference-techniques/index.json'
    reference_parts = []
    if decomposition_path.exists():
        decomposition = read_json(decomposition_path)
        audit['inputs'].append(evidence(decomposition_path))
        for entry in decomposition['parts']:
            ident = 'v3:' + entry['id']
            source = ROOT.parent / entry['source']
            sid = add_source(source, group='已拆解参考建筑')
            schem = ROOT.parent / entry['schematic']
            if not sid or sources[sid]['sha256'] != entry['source_sha256'] or digest(schem) != entry['schematic_sha256']:
                audit['issues'].append({'kind': 'decomposition_hash_mismatch', 'id': ident})
            data = load_schematic(schem)
            counts = {s:n for s,n in data.exact_state_counts().items()
                      if s not in ('minecraft:air','minecraft:cave_air','minecraft:void_air')}
            if counts != entry['inventory']['exact_states']:
                audit['issues'].append({'kind': 'decomposition_state_mismatch', 'id': ident})
            is_facade = entry.get('kind') == 'facade_segment'
            hero = 'axonometric_back' if entry['outside'] == 'south/+z' else 'axonometric_front'
            refs = [evidence(decomposition_path, entry['id']), evidence(source, str(entry['source_bbox_xyz_half_open'])),
                    evidence(schem, '目标版本裁件'), evidence(schem.parent / 'record.json', '拆解与清洗账目')]
            item = record(ident, 'facade' if is_facade else 'component', entry['title'], entry['observation'], refs,
                origin='source_decomposition', claim_status=entry['claim_status'],
                family=entry['families'][0] if entry['families'] else 'facade_composition',
                families=entry['families'], dimensions=entry['inventory']['dimensions_whd'],
                image=(schem.parent / 'previews' / (hero+'.png')).relative_to(ROOT.parent).as_posix(),
                schematic=entry['schematic'], sources=[sid] if sid else [],
                states=list(counts), content_hash=data.voxel_state_hash(), raw=entry,
                compatible_vanilla=entry['compatible_vanilla'], retrieval_eligible=entry['compatible_vanilla'],
                constraints=[entry['constraint'],entry['compatibility_note'],'冻结方块状态；游戏内验收未运行'],
                observations=[f"源坐标 {entry['source_bbox_xyz_half_open']}；室外方向 {entry['outside']}",
                              f"{sum(counts.values())} 个非空气方块；逐格回读与转换记录已核对"],
                inferences=[entry['observation']], links=[m['technique_id'] for m in entry['library_matches']])
            records.append(item)
            reference_parts.append(item)

    from .facade import SCHEMES
    from .technique import SCHEME_TECHNIQUES
    for form, (title, summary) in FORMS.items():
        records.append(record('structure:' + form, 'structure', title, summary,
            [evidence(ROOT / 'src/paris_builder/house.py', form),
             evidence(ROOT / 'reports/HOUSE_DESIGN_LAYERS.md', '结构形式')],
            observations=['项目已有此结构生成实现'], inferences=[summary],
            constraints=['这是既有设计归纳，尚非逐栋语义标注完成的源事实'], raw={'form': form}))
    for name, (title, summary) in FACADES.items():
        records.append(record('facade:' + name, 'facade', title, summary,
            [evidence(ROOT / 'src/paris_builder/facade.py', name)], raw=asdict(SCHEMES[name]),
            links=['technique:' + ({'guard_rail': 'railing', 'door_leaf': 'door', 'quoins': 'quoin'}.get(x, x))
                   for x in SCHEME_TECHNIQUES[name]], inferences=[summary],
            constraints=['开口、窗台、层线与楼层标高需在具体墙面上试装']))
    style_path = ROOT / 'knowledge/styles/paris_haussmann_v0.1.json'
    style = read_json(style_path)
    for rule in style['invariants']:
        title, summary = RULES[rule['id']]
        records.append(record('style:' + rule['id'], 'facade', title, summary,
            [evidence(style_path, rule['id'])], raw=rule, origin='style_research',
            constraints=['历史风格研究摘录，外部来源未在本轮重新核查'],
            inferences=[summary], external_sources=[x for x in style['external_sources'] if x['id'] in rule['evidence']]))
    for family, label in catalog['families'].items():
        examples = [r for r in records if r.get('family') == family and r['origin'] == 'derived_recipe']
        source_examples = [r for r in reference_parts if family in r['families']]
        refs = [evidence(catalog_path, 'families.' + family)]
        if source_examples:
            refs.append(evidence(decomposition_path, family))
        records.append(record('technique:' + family, 'technique', label,
            f'{label}（{family}）：已有 {len(examples)} 个派生配方、{len(source_examples)} 个带坐标和状态的参考建筑拆件。可对照形状、进深和连接方式。', refs,
            family=family, links=[r['id'] for r in source_examples + examples],
            sources=sorted({s for r in source_examples + examples for s in r['sources']}),
            image=examples[0]['image'] if examples else None,
            observations=[f'库内存在 {len(examples)} 个配方'],
            constraints=['配方的来源类比不等于源作品全部技法已被解释', '需要记录支撑、遮挡、视角和更新条件'],
            raw={'family': family, 'examples': [r['id'] for r in examples],
                 'source_examples': [r['id'] for r in source_examples]}))
    for r in records:
        for sid in r['sources']: sources[sid]['count'] += 1
        r['duplicate_ids'] = [x for x in hashes.get(r.get('content_hash'), []) if x != r['id']]
    excluded_path = ROOT / 'knowledge/library-v2/details/exclusions.json'
    audit.update({'detail_count': len(detail_data['details']), 'legacy_count': len(catalog['windows']) + len(catalog['recipes']),
                  'reference_decomposition_count': len(reference_parts),
                  'legacy_crops_quarantined': len(legacy_issues),
                  'unique_v2_geometry': len(hashes), 'duplicate_v2_records': sum(len(v)-1 for v in hashes.values()),
                  'excluded_cuts': len(read_json(excluded_path)), 'excluded_path': evidence(excluded_path),
                  'limitations': ['优秀与否未由状态数量自动判定', '结构与立面现阶段为既有规则归纳',
                                 '源裁件语义与朝向待复核', '无游戏内验收结论']})
    if audit['issues']:
        raise ValueError('Evidence audit failed: ' + json.dumps(audit['issues'][:8], ensure_ascii=False))
    return records, list(sources.values()), audit


def embedding_text(r):
    # Compact meaning, never the full block/NBT inventory. Exact evidence stays in SQLite.
    return ' '.join([LAYERS[r['layer']], r['title'], r['summary'], FAMILY_MEANINGS.get(r.get('family'), ''),
                     ' '.join(r.get('states', [])[:4])])


def build_database(path=DB):
    records, sources, audit = collect_records()
    records.sort(key=lambda r: r['id'])
    vectors = SemanticEncoder(ROOT / 'knowledge/retrieval/model').encode([embedding_text(r) for r in records])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {'created_at': now(), 'count': len(records), 'layers': dict(Counter(r['layer'] for r in records)),
            'source_count': len(sources), 'model': MODEL_ID, 'revision': MODEL_REVISION,
            'vector_dimension': int(vectors.shape[1]), 'audit': audit}
    with sqlite3.connect(path) as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, layer TEXT, payload TEXT, vector BLOB);
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, payload TEXT);
            CREATE TABLE IF NOT EXISTS reviews (id TEXT PRIMARY KEY, status TEXT, note TEXT, at TEXT);
            CREATE TABLE IF NOT EXISTS annotations (id TEXT PRIMARY KEY, payload TEXT, record_hash TEXT, at TEXT);
            CREATE TABLE IF NOT EXISTS annotation_vectors (id TEXT PRIMARY KEY, record_hash TEXT, vector BLOB);''')
        db.execute('DELETE FROM records')
        db.executemany('INSERT INTO records VALUES (?,?,?,?)',
            [(r['id'], r['layer'], json.dumps(r, ensure_ascii=False), v.astype('<f4').tobytes()) for r, v in zip(records, vectors)])
        for key, value in [('manifest', meta), ('sources', sources)]:
            db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, json.dumps(value, ensure_ascii=False)))
    (path.parent / 'manifest.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    return meta


class KnowledgeIndex:
    def __init__(self, path=DB):
        self.path = Path(path)
        with sqlite3.connect(self.path) as db:
            self.meta = json.loads(db.execute("SELECT payload FROM meta WHERE key='manifest'").fetchone()[0])
            self.sources = json.loads(db.execute("SELECT payload FROM meta WHERE key='sources'").fetchone()[0])
            rows = db.execute('SELECT payload, vector FROM records ORDER BY id').fetchall()
        self.records = [json.loads(x[0]) for x in rows]
        self.by_id = {r['id']: r for r in self.records}
        self.vectors = np.stack([np.frombuffer(x[1], dtype='<f4') for x in rows])
        self.encoder = None
        self.lock = threading.Lock()
        self.positions = {r['id']: i for i, r in enumerate(self.records)}

    def reviews(self):
        with sqlite3.connect(self.path) as db:
            return {i: {'status': s, 'note': n, 'at': a} for i, s, n, a in db.execute('SELECT * FROM reviews')}

    def query(self, text='', layer=None, source=None, max_width=None, vanilla=False,
              quality=None, limit=24, offset=0):
        if layer and layer not in LAYERS: raise ValueError('Unknown knowledge layer')
        reviews = self.reviews()
        similarity = np.zeros(len(self.records), dtype=np.float32)
        annotated = set()
        if text.strip():
            with self.lock:
                if self.encoder is None: self.encoder = SemanticEncoder(ROOT / 'knowledge/retrieval/model')
                query_vector = self.encoder.encode([text[:1000]])[0]
                similarity = self.vectors @ query_vector
            with sqlite3.connect(self.path) as db:
                annotations = db.execute('SELECT id,record_hash,vector FROM annotation_vectors').fetchall()
            for ident, record_hash, vector in annotations:
                # Only human-selected references may let AI interpretation change retrieval.
                if ident in self.by_id and reviews.get(ident, {}).get('status') == 'reference' and record_hash == self.record_hash(ident):
                    similarity[self.positions[ident]] = float(np.frombuffer(vector, dtype='<f4') @ query_vector)
                    annotated.add(ident)
        matches = []
        for i, r in enumerate(self.records):
            # Historical evidence remains available by ID, but suspect geometry
            # must not be recommended to a new design as a clean component.
            if r.get('retrieval_eligible') is False: continue
            review = reviews.get(r['id'], {'status': 'unreviewed', 'note': ''})
            if layer and r['layer'] != layer: continue
            if source and source not in r['sources']: continue
            if max_width is not None and (r['dimensions'] is None or r['dimensions'][0] > max_width): continue
            if vanilla and (r['layer'] != 'component' or not r.get('compatible_vanilla')): continue
            if quality and review['status'] != quality: continue
            if not quality and review['status'] == 'excluded': continue
            lexical = .12 if text.strip() and text.lower() in (r['title'] + ' ' + r.get('family', '')).lower() else 0
            matches.append({**{k: r[k] for k in ['id', 'layer', 'title', 'summary', 'origin', 'claim_status',
                                              'game_status', 'dimensions', 'image', 'sources', 'schematic']},
                            'review': review, 'score': round(float(similarity[i]) + lexical, 4),
                            'scores': {'semantic': round(float(similarity[i]), 4), 'exact_term_bonus': lexical,
                                       'reviewed_annotation_used': r['id'] in annotated}})
        matches.sort(key=lambda r: (-r['score'], r['id']))
        if text.strip():
            unique, seen = [], set()
            for item in matches:
                key = self.by_id[item['id']].get('content_hash', item['id'])
                if key in seen: continue
                seen.add(key)
                unique.append(item)
            matches = unique
        return {'total': len(matches), 'items': matches[offset:offset+limit], 'offset': offset,
                'method': 'local_multilingual_vector+exact_term+hard_filters' if text.strip() else 'catalogue',
                'score_note': '相似度用于排序，不代表质量评分或匹配概率'}

    def get(self, ident):
        if ident not in self.by_id: raise KeyError(ident)
        r = dict(self.by_id[ident])
        r['review'] = self.reviews().get(ident, {'status': 'unreviewed', 'note': ''})
        with sqlite3.connect(self.path) as db:
            row = db.execute('SELECT payload,record_hash FROM annotations WHERE id=?', (ident,)).fetchone()
        r['annotation'] = json.loads(row[0]) if row and row[1] == self.record_hash(ident) else None
        return r

    def record_hash(self, ident):
        return hashlib.sha256(json.dumps(self.by_id[ident], sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def review(self, ident, status, note):
        if ident not in self.by_id: raise KeyError(ident)
        if status not in ('unreviewed', 'reference', 'excluded'): raise ValueError('Unknown review status')
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT OR REPLACE INTO reviews VALUES (?,?,?,?)', (ident, status, note[:2000], now()))

    def save_annotation(self, ident, data):
        with self.lock:
            if self.encoder is None: self.encoder = SemanticEncoder(ROOT / 'knowledge/retrieval/model')
            vector = self.encoder.encode([self.by_id[ident]['title'] + ' ' + data['proposal']['summary']])[0]
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT OR REPLACE INTO annotations VALUES (?,?,?,?)',
                       (ident, json.dumps(data, ensure_ascii=False), self.record_hash(ident), now()))
            db.execute('INSERT OR REPLACE INTO annotation_vectors VALUES (?,?,?)',
                       (ident, self.record_hash(ident), vector.astype('<f4').tobytes()))
