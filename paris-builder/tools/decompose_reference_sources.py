"""Build reviewable, lossless reference crops with explicit technique-library links."""
from pathlib import Path
import argparse
import hashlib
import html
import json
import os
import subprocess
import sys
from collections import Counter
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from paris_builder.source_decomposition import crop, encode, inventory, state_context, family_matches, migrate_to_12111
from paris_builder.schematic import load_schematic, _plain
from paris_builder.exporter import write_schematic, dump_json
from paris_builder.fonts import node_binary
from paris_builder.preview3d import render_previews

OUT = ROOT / 'knowledge/library-v3/reference-techniques'
SPEC = ROOT / 'knowledge/reference-decomposition/spec.json'
VIEWS = ['front', 'back', 'left', 'right', 'top', 'axonometric_front', 'axonometric_back']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path):
    return path.relative_to(ROOT.parent).as_posix()


def context_entities(data, bbox):
    kept = []
    for entry in data.block_entities:
        entry = _plain(entry)
        pos = entry.get('Pos', entry.get('pos'))
        if pos is not None and len(pos) == 3 and all(bbox[i] <= int(pos[i]) < bbox[i+3] for i in range(3)):
            kept.append(entry)
    return {'block_entities_in_crop': kept, 'source_block_entity_count': len(data.block_entities),
            'policy': 'source NBT retained here as context; exported schematics carry block geometry only',
            'source_entities': _plain(data.entities)}


def page(out, records, sources):
    esc = html.escape
    cards = []
    for r in records:
        ident = r['id']
        families = '、'.join(m['label'] for m in r['library_matches']) or '立面构图分段'
        hero = 'axonometric_back' if r['outside'] == 'south/+z' else 'axonometric_front'
        views = ''.join(f'<a href="{ident}/previews/{v}.png"><img loading="lazy" src="{ident}/previews/{v}.png" alt="{v}"><span>{v}</span></a>' for v in VIEWS)
        state_rows = ''.join(f'<tr><td>{esc(s)}</td><td>{n}</td></tr>' for s,n in r['inventory']['exact_states'].items())
        cards.append(f'''<article data-search="{esc(r['title']+' '+families+' '+r['observation'])}" data-source="{r['source_id']}">
        <img class="hero" loading="lazy" src="{ident}/previews/{hero}.png"><div class="body">
        <small>{esc(r['source_id'])} · {esc(families)}</small><h2>{esc(r['title'])}</h2>
        <p>{esc(r['observation'])}</p><p class="constraint">{esc(r['constraint'])}</p>
        <p>{' × '.join(map(str,r['inventory']['dimensions_whd']))} 格 · {r['inventory']['nonair']} 非空气方块 · {len(r['inventory']['exact_states'])} 种状态</p>
        <p>源坐标 {r['source_bbox_xyz_half_open']} · 外侧 {r['outside']}</p>
        <p>原裁件逐格一致：{r['validation']['source_states_equal']} · 目标版本转换已核对：{r['validation']['documented_transform_equal']} · 独立读取：{r['validation']['registry_status']} · 游戏验证：未运行</p>
        <p>{esc(r['compatibility_note'])}</p>
        <a href="{ident}/detail.schem">清洗裁件</a> · <a href="{ident}/source-crop.schem">原范围裁件</a> · <a href="{ident}/record.json">来源、状态与匹配记录</a>
        <details><summary>七视角与方块状态</summary><div class="views">{views}</div><table>{state_rows}</table></details></div></article>''')
    source_rows = ''.join(f'<tr><td>{esc(s["name"])}</td><td>{s["air_palette_ids"]}</td><td>{s["nonair"]:,}</td><td>{s["fill_ratio"]:.2%}</td></tr>' for s in sources)
    text = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>参考建筑手法拆解</title><style>body{margin:0;background:#f1f2ef;color:#23332f;font:16px/1.65 system-ui,sans-serif}header,main{max-width:1250px;margin:auto;padding:28px}h1{font-size:32px;margin:0}h2{font-size:21px}small{color:#557568}.note{max-width:850px}input,select{font:inherit;padding:9px;border:1px solid #b5c6ba;border-radius:8px;margin:8px 8px 8px 0}article{display:grid;grid-template-columns:330px 1fr;background:white;border:1px solid #d4ddd6;border-radius:12px;margin:20px 0;overflow:hidden}.hero{width:100%;height:330px;object-fit:contain;background:#e5ebef}.body{padding:24px}.constraint{padding:10px;background:#f7f1df}.views{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.views img{width:100%;height:180px;object-fit:contain}.views a{font-size:12px;text-align:center}a{color:#1b6d55}table{border-collapse:collapse;max-width:100%;font-size:12px}td,th{border-bottom:1px solid #dce3dd;padding:5px;text-align:left;overflow-wrap:anywhere}details{margin-top:15px}summary{cursor:pointer}article[hidden]{display:none}@media(max-width:800px){article{display:block}.views{grid-template-columns:repeat(2,1fr)}header,main{padding:15px}}</style>
    <header><h1>参考建筑手法拆解</h1><p class="note">从街区3和建筑素材2的实际方块中拆出构图单元与手法样本。每件保留源坐标、精确状态、清洗账目和现有手法库匹配。这里展示的是可追溯的学习材料；裁件的截面、特殊状态和拼接条件都需要结合原建筑理解。</p>
    <p class="note">清洗移除外围空气并压缩调色板；旧版 chain 按目标版本改名为 iron_chain，属性和改动坐标逐格留账。门叶、墙肢、楼梯等特殊状态保留。含模组方块的样本仅供追溯，不能当成原版可用件。游戏内验收未运行。</p>
    <table><tr><th>参考源</th><th>空气编号</th><th>非空气方块</th><th>真实填充率</th></tr>'''+source_rows+'''</table>
    <input id="q" placeholder="搜索：老虎窗、檐口、基座…"><select id="s"><option value="">全部参考源</option><option>street3</option><option>building2</option></select><span id="count"></span>
    <p><a href="index.json">完整索引</a> · <a href="validation.json">验证记录</a></p></header><main>'''+''.join(cards)+'''</main><script>function filter(){let n=0;document.querySelectorAll('article').forEach(a=>{a.hidden=!(a.dataset.search.includes(document.querySelector('#q').value)&&(!document.querySelector('#s').value||a.dataset.source===document.querySelector('#s').value));if(!a.hidden)n++});document.querySelector('#count').textContent=n+' 件'}document.querySelector('#q').oninput=filter;document.querySelector('#s').onchange=filter;filter()</script></html>'''
    (out / 'index.html').write_text(text, encoding='utf-8')


def review_sheets(out, records):
    # Four parts per sheet, seven views per part: every source crop is inspectable.
    for start in range(0, len(records), 4):
        subset = records[start:start+4]
        sheet = Image.new('RGB', (1750, 320 * len(subset)), '#e5ebef')
        draw = ImageDraw.Draw(sheet)
        for row, r in enumerate(subset):
            draw.text((8,row*320+4), r['id'], fill='black')
            for col, view in enumerate(VIEWS):
                path = out / r['id'] / 'previews' / (view+'.png')
                if not path.exists():
                    continue
                with Image.open(path) as opened:
                    im = opened.convert('RGB')
                im.thumbnail((248,282))
                sheet.paste(im, (col*250+(250-im.width)//2,row*320+28+(282-im.height)//2))
                draw.text((col*250+6,row*320+17),view,fill='black')
        sheet.save(out / ('review-sheet-%02d.png' % (start//4+1)))


def legacy_audit(out):
    survey_path=ROOT/'runs/REFERENCE-DECOMPOSITION-v1/survey.json'
    if not survey_path.exists():
        raise ValueError('Run corrected survey_incoming.py before decomposition')
    survey={r['source']:r for r in json.loads(survey_path.read_text(encoding='utf-8'))}
    old=json.loads((ROOT/'knowledge/library-v2/details/index.json').read_text(encoding='utf-8'))['details']
    records={}
    for entry in old:
        reasons=[]
        if 0 not in survey[entry['source']]['air_palette_ids']:
            reasons.append('旧拆件器曾把源调色板0号实体误当空气；需重新提取后再参与推荐。')
        if entry['normalisations']['door_halves_fixed']:
            reasons.append('旧清洗改写了门叶half属性，但尚未证明这些门叶属于功能门而非装饰；需对照源状态重拆。')
        if reasons:
            records['v2:'+entry['detail_id']]=reasons
    dump_json(out/'legacy_audit.json',{'survey_path':relative(survey_path),'survey_sha256':digest(survey_path),
        'records':records,'quarantined_count':len(records),
        'policy':'keep historical files and direct ID access; omit these suspect crops from new design recommendations'})


def measured_rules(out, sources, records):
    data=sources['street3']
    palette=np.asarray(data.id_to_state,dtype=object)
    grid=palette[data.volume]
    def groups(values):
        result=[]
        for value in values:
            value=int(value)
            if result and result[-1][1]==value:
                result[-1][1]=value+1
            else:
                result.append([value,value+1])
        return result
    windows=np.array(['_door[' in str(s) for s in grid[22,26:28,66:89].ravel()]).reshape(2,23)
    xgroups=groups(np.nonzero(windows.any(axis=0))[0]+66)
    ycounts=[sum('_door[' in str(s) for s in grid[y,26:28,66:89].ravel()) for y in range(7,41)]
    bands=groups(np.nonzero(ycounts)[0]+7)
    roof=[]
    for z in range(9,30):
        cells=[y for y in range(35,48) for x in range(80,84) if 'deepslate' in str(grid[y,z,x])]
        if cells:
            roof.append({'source_z':z,'top_y':max(cells)})
    dump_json(out/'measured_rules.json',{
        'source_id':'street3','source_sha256':digest(data.path),
        'facade_sample_bbox_xyz_half_open':[66,1,22,89,50,32],
        'window_surface_sample':{'source_y':22,'source_z_half_open':[26,28],
            'door_model_x_bands_half_open':xgroups,'start_pitch':[b[0]-a[0] for a,b in zip(xgroups,xgroups[1:])],
            'note':'door-shaped blocks visually form the window surface; this measurement does not classify them as working doors'},
        'window_surface_y_bands_half_open':bands,'roof_material_profile':roof,
        'interpretations':[
            '样本的窗组起点间距为4、5、5、4格，形成两侧较密、中央略宽的节奏；主体窗层起点为8、14、20、26格，顶部另行处理。',
            '铁门在这里是薄窗面手法；半扇状态、朝向和前后层必须作为整体保留。',
            '阳台板、护栏和窗面不在同一进深；裁件侧视比材料名称更能说明构法。',
            '屋面陡段承载直立窗，往上减缓，不能用固定宽度的深色竖块增加屋顶高度。',
            '12格单栋应按完整开间和两侧墙墩重组；参考的23格街面单元不整体缩放。'],
        'evidence_parts':[r['id'] for r in records if r['source_id']=='street3'],
        'limits':['用途为单栋设计约束参考，不自动推出完整房屋方案','只核对本轮两组参考源，未证明14源穷尽']})


def apply_visual_review(out, records):
    path=out/'visual_review.json'
    reviews=json.loads(path.read_text(encoding='utf-8')).get('parts',{}) if path.exists() else {}
    for r in records:
        review=reviews.get(r['id'])
        if not review or review['schematic_sha256']!=r['schematic_sha256']:
            continue
        if set(review['views'])!=set(VIEWS) or any(
                digest(out/r['id']/'previews'/(v+'.png'))!=review['views'][v]['sha256'] for v in VIEWS):
            continue
        r['role_review']={'reviewer':'Codex visual inspection','reviewer_type':'agent',
            'decision':review['decision'],'finding':review['finding'],
            'evidence':relative(path),'game_acceptance':'NOT_RUN'}
        r['claim_status']='SOURCE_STATES_VERIFIED_VISUALLY_INTERPRETED'
        dump_json(out/r['id']/'record.json',r)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--render', action='store_true')
    parser.add_argument('--only', nargs='*')
    parser.add_argument('--refresh-metadata', action='store_true',
                        help='refresh measurements, review bindings and page without rebuilding unchanged geometry')
    args = parser.parse_args()
    spec = json.loads(SPEC.read_text(encoding='utf-8'))
    catalog = json.loads((ROOT / 'knowledge/library-v1/catalog.json').read_text(encoding='utf-8'))
    sources, source_meta, parts = {}, {}, list(spec['parts'])
    OUT.mkdir(parents=True, exist_ok=True)
    for entry in spec['sources']:
        path = ROOT.parent / entry['path']
        data = load_schematic(path)
        sources[entry['id']] = data
        source_meta[entry['id']] = {**entry, 'name': path.name, 'sha256': digest(path),
            'nonair': int(data.nonair_mask().sum()), 'fill_ratio': float(data.nonair_mask().mean()),
            'air_palette_ids': data.air_ids.tolist(), 'offset_xyz': list(data.offset),
            'dimensions_whd': [data.width,data.height,data.length]}
        boundaries = entry['frontage_segments']
        for i,(left,right) in enumerate(zip(boundaries,boundaries[1:])):
            parts.append({'id': entry['id']+'-facade-'+str(i+1), 'source':entry['id'],
                'parent': entry['id'], 'bbox':[left,1,entry['street_depth'][0],right,data.height,entry['street_depth'][1]],
                'title':path.stem+' · 街面构图分段 '+str(i+1), 'families':[],
                'observation':entry['segment_note'],
                'constraint':'这是街面壳层，侧面和背面为裁切面；屋面和室内深处需查阅完整源文件。',
                'kind':'facade_segment'})
    records = []
    for part in parts:
        folder = OUT / part['id']
        if args.refresh_metadata:
            saved=json.loads((folder/'record.json').read_text(encoding='utf-8'))
            if saved['source_sha256']!=source_meta[part['source']]['sha256'] or saved['bbox']!=part['bbox'] or digest(folder/'detail.schem')!=saved['schematic_sha256']:
                raise ValueError('Geometry changed; rebuild '+part['id'])
            records.append(saved)
            continue
        if args.only and part['id'] not in args.only:
            if (folder/'record.json').exists():
                records.append(json.loads((folder/'record.json').read_text(encoding='utf-8')))
            continue
        folder.mkdir(parents=True,exist_ok=True)
        data = sources[part['source']]
        raw, cleaned, offset, cleaning = crop(data, part['bbox'])
        original_inventory = inventory(cleaned)
        cleaned, migrations = migrate_to_12111(cleaned, offset)
        cleaning['version_migrations'] = migrations
        cleaning['changed_nonair_cells'] = len(migrations)
        cleaning['policy'] = 'PRESERVE_SOURCE_WITH_EXPLICIT_TARGET_VERSION_RENAMES'
        for filename, grid in [('source-crop.schem',raw),('detail.schem',cleaned)]:
            volume, palette = encode(grid)
            write_schematic(folder/filename,volume,palette,name=part['id'],
                            data_version=data.data_version if filename=='source-crop.schem' else 4671)
        read = load_schematic(folder/'detail.schem')
        actual = np.asarray(read.id_to_state,dtype=object)[read.volume]
        transformed_equal = bool(np.array_equal(actual,cleaned))
        raw_read=load_schematic(folder/'source-crop.schem')
        source_equal=bool(np.array_equal(np.asarray(raw_read.id_to_state,dtype=object)[raw_read.volume],raw))
        if not source_equal or not transformed_equal:
            raise ValueError('Export changed source states: '+part['id'])
        context = context_entities(data, part['bbox'])
        dump_json(folder/'source-nbt-context.json',context)
        registry = folder/'registry.json'
        result = subprocess.run([node_binary(),str(ROOT/'tools/validate_schematic.cjs'),
            str(folder/'detail.schem'),str(registry)],capture_output=True,text=True,
            encoding='utf-8',errors='replace',timeout=120)
        check = json.loads(registry.read_text(encoding='utf-8')) if registry.exists() else {'status':'FAIL','issues':[result.stderr]}
        inv = inventory(cleaned)
        r = {**part, 'source_id':part['source'], 'source':source_meta[part['source']]['path'],
             'source_sha256':source_meta[part['source']]['sha256'],
             'outside':source_meta[part['source']]['outside'], 'source_bbox_xyz_half_open':part['bbox'],
             'clean_origin_source_xyz':offset, 'inventory':inv,'source_inventory':original_inventory,'cleaning':cleaning,
             'state_context':state_context(data,cleaned,offset),
             'library_matches':family_matches(part['families'], inv['exact_states'],catalog),
             'schematic':relative(folder/'detail.schem'), 'schematic_sha256':digest(folder/'detail.schem'),
             'raw_schematic':relative(folder/'source-crop.schem'),
             'validation':{'source_states_equal':source_equal,'documented_transform_equal':transformed_equal,'registry_status':check['status'],
                           'registry_issues':check.get('issues',[]),'game_acceptance':'NOT_RUN'},
             'claim_status':'SOURCE_STATES_VERIFIED_SEMANTICS_ANNOTATED',
             'role_review':'PENDING_VISUAL_REVIEW',
             'compatible_vanilla':check['status']=='PASS',
             'compatibility_note':'目标版本方块注册表通过；装配与游戏行为尚需验证。' if check['status']=='PASS' else '含未转译模组方块：仅保留源证据，排除原版直接装配；预览中的替代模型不算原模型验证。',
             'entity_scope':'block geometry only; source NBT in source-nbt-context.json'}
        record_path=folder/'record.json'
        dump_json(record_path,r)
        if args.render:
            metadata=folder/'previews/render_metadata.json'
            cached=json.loads(metadata.read_text(encoding='utf-8')) if metadata.exists() else {}
            if cached.get('source_sha256') != r['schematic_sha256']:
                render_previews(folder/'detail.schem',folder/'previews',max_size=700)
        records.append(r)
        print(part['id'],inv['dimensions_whd'],inv['nonair'],check['status'],flush=True)
    unchanged=all(digest(sources[k].path)==meta['sha256'] for k,meta in source_meta.items())
    apply_visual_review(OUT,records)
    validation={'source_files_unchanged':unchanged,'parts':len(records),
        'source_state_roundtrips':sum(r['validation']['source_states_equal'] for r in records),
        'registry_pass':sum(r['validation']['registry_status']=='PASS' for r in records),
        'visually_reviewed_parts':sum(isinstance(r['role_review'],dict) for r in records),
        'changed_nonair_cells':sum(r['cleaning']['changed_nonair_cells'] for r in records),
        'unique_source_cells_version_renamed':len({(r['source_id'],tuple(c['source_xyz'])) for r in records for c in r['cleaning']['version_migrations']}),
        'technique_families':sorted({f for r in records for f in r['families']}),
        'game_acceptance':'NOT_RUN','scope':'two reference sources; annotated sample cuts, not exhaustive source semantics'}
    dump_json(OUT/'index.json',{'schema':spec['schema'],'sources':list(source_meta.values()),'parts':records})
    dump_json(OUT/'validation.json',validation)
    legacy_audit(OUT)
    measured_rules(OUT,sources,records)
    page(OUT,records,list(source_meta.values()))
    if args.render:
        review_sheets(OUT,records)
    print(json.dumps(validation,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
