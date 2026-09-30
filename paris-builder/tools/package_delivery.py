#!/usr/bin/env python3
"""Make readable review artifacts without claiming in-game acceptance."""
from pathlib import Path
import argparse,json,hashlib,shutil
from collections import Counter
from PIL import Image,ImageDraw
from paris_builder.exporter import dump_json
from paris_builder.fonts import load_font
ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path);a=p.parse_args();out=a.directory
    lab=json.loads((out/'state_lab_tests.json').read_text(encoding="utf-8"));plots=lab['plots']
    plan=json.loads((out/'assembly_plan.json').read_text( encoding="utf-8"));manifest=json.loads((out/'manifest.json').read_text( encoding="utf-8"))
    font=load_font(18)
    rows=(len(plots)+11)//12;im=Image.new('RGB',(1440,100+rows*80),'#edf1f4');d=ImageDraw.Draw(im)
    d.text((20,15),'STATE-LAB / north (-z) at top / x increases right',font=font,fill='black')
    d.text((20,42),'Gold block marks northwest corner. Numbers follow rows, then columns.',font=font,fill='black')
    for e in plots:
        i=e['plot']-1;x=(i%12)*120;y=90+(i//12)*80
        d.rectangle((x+4,y,x+115,y+73),outline='#7b8b96',width=2)
        d.rectangle((x+9,y+5,x+18,y+14),fill='#dbab29')
        d.text((x+25,y+7),f"{i+1:03d}",font=font,fill='black')
        xx,yy,zz=e['centre_xyz'];d.text((x+10,y+38),f'{xx},4,{zz}',font=font,fill='#435363')
    im.save(out/'STATE-LAB-map.png')
    lines=['# 更新风险与实测记录','','全部状态为待测。以下是实验位置，不是已证实必须禁止更新的清单。','',
           '|编号|局部中心 x,y,z|分类|构件|正常/禁止/邻变/重载|','|---|---|---|---|---|']
    for e in plots:lines.append(f"|{e['plot']:03d}|{e['centre_xyz']}|{e['technical_category']}|{e['owner']}|待测/待测/待测/待测|")
    (out/'更新风险表.md').write_text('\n'.join(lines)+'\n', encoding="utf-8")
    rows=['# 构件来源与变换','','派生组合保留原手法证据；不表示复制了原作品的构件。',
          '|构件|实例数|来源|','|---|---|---|']
    groups={}
    for p in plan['placements']:
        item=groups.setdefault(p['component_id'],{'count':0,'evidence':p.get('evidence',[])})
        item['count']+=1
    for key,item in sorted(groups.items()):rows.append(f"|{key}|{item['count']}|{json.dumps(item['evidence'],ensure_ascii=False)}|")
    (out/'构件来源表.md').write_text('\n'.join(rows)+'\n', encoding="utf-8")
    dump_json(out/'design_seeds.json',{'seeds':manifest['seeds'],'scheme':manifest['scheme'],'concept':plan['concept'],
          'decisions':plan['decision_trace'],'acceptance':'USER_PENDING'})
    materials=json.loads((out/'materials.json').read_text(encoding="utf-8"))
    (out/'材料表.md').write_text('# 材料表\n\n|方块|数量|\n|---|---:|\n'+'\n'.join(f'|{k}|{v}|' for k,v in sorted(materials.items(),key=lambda p:-p[1]))+'\n', encoding="utf-8")
    refs=out/'reference-comparisons';refs.mkdir(exist_ok=True)
    for source in (ROOT.parent/'参考图').glob('标准*.png'):shutil.copy2(source,refs/source.name)
    # Same orthographic renderer cameras; image sizes are retained, not confused
    # with an equal metric-scale comparison across differently sized buildings.
    for name in ('front','axonometric_front','axonometric_back','back'):
        shutil.copy2(out/'previews'/f'{name}.png',refs/f'PAR-002_{name}.png')
    atlas=ROOT.parent/'参考图'/'窗对照总览_街面.png'
    if not atlas.exists():atlas=ROOT.parent/'窗对照总览_街面.png'
    if atlas.exists():shutil.copy2(atlas,refs/atlas.name)
    for name in ('framework_review.json','facade_review.json','detail_review.json'):
        shutil.copy2(out.parent/name,out/name)
    report={'technical_checks':{name:json.loads((out/name).read_text( encoding="utf-8")).get('status','SEE_REPORT') for name in
        ('validation.json','independent_validation.json','geometry_validation.json','frozen_state_validation.json','originality_audit.json')},
        'component_library':json.loads((ROOT/'knowledge/library-v1/production_audit.json').read_text( encoding="utf-8"))['status'],
        'component_library_files':178,'window_interpretations':43,'derived_families':45,'derived_variants':135,
        'local_contexts':'Index only; full semantic exhaustiveness NOT_PROVEN',
        'game_tests':'NOT_RUN','user_acceptance':'PENDING','production_stability':'UNVERIFIED'}
    coverage=json.loads((ROOT/'knowledge/library-v1/exhaustive-contexts/coverage.json').read_text(encoding="utf-8"))
    report['source_scan']={'sources':len(coverage['sources']),'nonair_positions':sum(r['nonair_positions_scanned'] for r in coverage['sources']),
        'unique_local_contexts':coverage['unique_contexts'],'semantic_exhaustiveness':coverage['semantic_exhaustiveness']}
    shutil.copy2(ROOT/'knowledge/library-v1/exhaustive-contexts/coverage.json',out/'source_context_coverage.json')
    dump_json(out/'release_report.json',report)
    guide='''# PAR-002 游戏验收包

本包是游戏验收候选，未标记最终合格。目标：Minecraft Java 1.21.11 / DataVersion 4671。

## 两个文件

- PAR-002.schem：外立面、转角、院面、服务面、屋顶及窗后可见进深；没有完整室内。
- STATE-LAB.schem：同一文件粘贴两次，分别正常更新与禁止更新。编号见 STATE-LAB-map.png；金块是每格西北角，中心坐标见更新风险表。复制的是半径2的真实邻域，边界可能截断门和其他构件，只评价中央目标状态。

## 粘贴

先用 `/worldedit version` 记录平台与版本，用 `//perf` 查看实际支持的开关。以下适用于提供这些开关的 WorldEdit；FAWE 或其他工具请按其实际更新控制操作，不能把名称相近的快速模式当作已证明等价。

1. 将两个 schem 放到当前实例的 WorldEdit schematics 目录。选空白测试场地，保留足够边界。
2. 正常组：`//perf neighbors on`、`//perf update on`；`//schem load STATE-LAB`，`//paste`。
3. 禁止更新组：换到不重叠场地，`//perf neighbors off`、`//perf update off`；同一文件 `//paste`。
4. 保留禁止更新开关，`//schem load PAR-002`，`//paste`。建议包括空气粘贴，确保窗洞和院落没有被原场地方块填上。
5. 记录刚粘贴的状态及外观，再在实验组目标旁放置/移除方块，并离开足够远让区块卸载后返回。开关只约束粘贴期间，不能保证随后手动邻接变化稳定。
6. 检查完成后恢复自己原来的 perf 设置。

命令来源：[WorldEdit 官方命令文档](https://worldedit.enginehub.org/en/latest/commands/)；开关名称核对了 [SideEffect 源码](https://github.com/EngineHub/WorldEdit/blob/master/worldedit-core/src/main/java/com/sk89q/worldedit/util/SideEffect.java)。具体服务端行为仍由本次 A/B 决定。

## 验收顺序

沿八个方向检查地面与高处；近看窗套薄片、栏杆、楼梯托件、花箱和悬空雨棚；检查45度转角、内院四面、入口、屋顶交接和烟囱。最后检查重载后的同机位。外立面正式程度应按主街、侧街、院面和服务面递减。

记录失败时提供：实验编号或建筑局部坐标、观察方向、何时发生变化、期望造型。接受/拒绝写入 game_acceptance.json。只有用户明确通过才能把状态改为 ACCEPTED。

## 证据边界

三验、逐坐标回读和字节复现已记录；真实方块模型预览不模拟游戏邻接更新和客户端完整光照。178件构件已做文件与注册表检查，游戏验证仍待测。14源作品的状态/局部上下文已索引，不能把索引数量说成所有建筑语义都已理解。原创性报告是有限网格抽查，不是穷举证明。
'''
    (out/'开始验收.md').write_text(guideencoding="utf-8")
    dump_json(out/'game_acceptance.json',{'status':'PENDING','minecraft':'1.21.11','data_version':4671,'worldedit_version':None,
          'normal_paste':None,'suppressed_paste':None,'neighbour_changes':None,'chunk_reload':None,'visual_acceptance':None,'rejections':[]})
    snapshot=out/'reproduction';snapshot.mkdir(exist_ok=True)
    shutil.copytree(ROOT/'src/paris_builder',snapshot/'paris_builder',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(ROOT/'knowledge/styles/paris_haussmann_v0.1.json',snapshot/'style_model.json')
    shutil.copy2(ROOT/'knowledge/library-v1/catalog.json',snapshot/'component_catalog.json')
    for filename in ('WORKFLOW_STYLE_LEARNING.md','knowledge/README.md','reports/PAR-002_execution.md'):
        shutil.copy2(ROOT/filename,out/(Path(filename).name if filename!='knowledge/README.md' else '知识库证据边界.md'))
    checks={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name!='checksums.json'}
    dump_json(out/'checksums.json',checks)
    print('Packaged',out,'lab plots',len(plots))

if __name__=='__main__':main()
