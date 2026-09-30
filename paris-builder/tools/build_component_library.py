#!/usr/bin/env python3
"""Build an auditable evidence catalogue and separate vanilla recipe library."""
from pathlib import Path
from collections import Counter, defaultdict
from dataclasses import asdict
import argparse
import hashlib
import json
import subprocess
import shutil
import numpy as np
from PIL import Image, ImageDraw

from paris_builder.architecture import split_state, state, digest
from paris_builder.components import FAMILIES, recipe
from paris_builder.exporter import dump_json, write_schematic
from paris_builder.schematic import load_schematic, AIR_BLOCKS
from paris_builder.preview3d import Assets, ensure_assets, _mesh, _render
from paris_builder.fonts import node_binary

ROOT=Path(__file__).resolve().parents[1]
WORKSPACE=ROOT.parent
NODE=node_binary()

def technique(s):
    name,p=split_state(s)
    for suffix,label in [('_wall','wall_connections'),('_pane','pane_connections'),('_stairs','stair_shapes'),
                         ('_slab','slab_halves'),('_fence_gate','gate_fragments'),('_trapdoor','thin_planes'),
                         ('_door','door_leaf_fragments'),('iron_bars','railing_connections')]:
        if name.endswith(suffix):return label
    return 'other_stateful' if p else 'solid_or_nonstateful'

def registry():
    script="const d=require('minecraft-data')('1.21.11');console.log(JSON.stringify(Object.fromEntries(d.blocksArray.map(b=>[b.name,{states:b.states,defaultState:b.defaultState,minStateId:b.minStateId}]))))"
    return json.loads(subprocess.check_output([NODE,'-e',script],cwd=ROOT,text=True,encoding='utf-8',errors='replace'))

def normalize(value,reg):
    name,props=split_state(value); short=name.split(':')[-1]; reason=None
    if not name.startswith('minecraft:'):
        for suffix,target in [('_wall','diorite_wall'),('_stairs','smooth_quartz_stairs'),('_slab','smooth_quartz_slab')]:
            if short.endswith(suffix): short=target;break
        else: short='calcite'
        reason='modded material translated; geometric family retained where available'
    if short not in reg:
        short='short_grass' if short=='grass' else 'stone'
        reason='legacy/unknown block explicitly translated'
    info=reg[short]; result={}; index=info['defaultState']-info['minStateId']
    defaults={}
    for spec in reversed(info['states']):
        ordinal=index%spec['num_values'];index//=spec['num_values']
        values=spec.get('values') or (['true','false'] if spec['type']=='bool' else [str(i) for i in range(spec['num_values'])])
        defaults[spec['name']]=str(values[ordinal])
    for spec in info['states']:
        key=spec['name'];values=list(map(str,spec.get('values') or (['true','false'] if spec['type']=='bool' else range(spec['num_values']))))
        result[key]=props.get(key,defaults[key])
        if result[key] not in values:
            result[key]=defaults[key];reason='invalid legacy property replaced with registry default'
    output=state(short,**result)
    return output,reason

def render_card(path,out,assets,title,outside='north'):
    out.mkdir(parents=True,exist_ok=True)
    mesh=_mesh(load_schematic(path),assets)
    sheet=Image.new('RGB',(840,760),(229,235,239))
    oblique=(1,.6,-1) if outside=='north' else (-1,.6,1)
    for i,(name,camera) in enumerate([('front',(0,0,-1)),('back',(0,0,1)),('oblique',oblique),('side',(1,0,0))]):
        dest=out/(name+'.png');_render(mesh,assets,camera,title+' / '+name,dest,420)
        tile=Image.open(dest).convert('RGB');tile.thumbnail((420,360))
        sheet.paste(tile,((i%2)*420,(i//2)*380))
    sheet.save(out/'card.png')
    return str((out/'card.png').relative_to(ROOT))

def sheet(paths,out,cols=6,tile=(230,220)):
    h=((len(paths)+cols-1)//cols)*tile[1]
    result=Image.new('RGB',(cols*tile[0],max(h,1)),'#e5ebef');draw=ImageDraw.Draw(result)
    for i,(label,path) in enumerate(paths):
        im=Image.open(path).convert('RGB');im.thumbnail((tile[0]-8,tile[1]-24))
        x=(i%cols)*tile[0];y=(i//cols)*tile[1]
        result.paste(im,(x,y+20));draw.text((x+4,y+3),label,fill='black')
    result.save(out)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'knowledge/library-v1')
    parser.add_argument('--skip-render',action='store_true');a=parser.parse_args()
    out=a.output;out.mkdir(parents=True,exist_ok=True);reg=registry()
    evidence=[];state_index=defaultdict(list);window_records=[];translations=[];all_states=set()
    assets=None if a.skip_render else Assets(ensure_assets())
    interpretations=json.loads((ROOT/'knowledge/window_visual_interpretations.json').read_text(encoding="utf-8"))
    cards=[]
    for path in sorted((WORKSPACE/'巴黎建筑素材').glob('*.schem')):
        src=load_schematic(path); counts=src.exact_state_counts(); clusters=[]
        for value,count in sorted(counts.items()):
            if value in AIR_BLOCKS:continue
            yy,zz,xx=np.where(src.volume==src.palette[value]); y,z,x=map(int,(yy[0],zz[0],xx[0]))
            bbox=[[max(0,x-2),max(0,y-2),max(0,z-2)],
                  [min(src.width-1,x+2),min(src.height-1,y+2),min(src.length-1,z+2)]]
            item={'state':value,'count':count,'technique':technique(value),'representative_xyz':[x,y,z],
                  'context_bbox_xyz':bbox,'semantic_status':'STATE_CLASSIFIED_CONTEXT_REQUIRES_VISUAL_INTERPRETATION',
                  'disposition':'STATE_EVIDENCE_INDEXED_NOT_MACRO_COMPONENT_COPY'}
            clusters.append(item);state_index[technique(value)].append({'source':str(path.relative_to(WORKSPACE)),**item})
        evidence.append({'source':str(path.relative_to(WORKSPACE)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
             'dimensions_xyz':[src.width,src.height,src.length],'block_entities':len(src.block_entities),
             'states':clusters,'coverage':'all nonair exact states; not a proof that all semantic assemblies were discovered',
             'excluded_instances':'repeated identical exact states counted; one context retained per source/state',
             'excluded_entity_reason':'behavioural NBT not transferred into generated recipes'})
        print('Indexed',path.name,flush=True)
    for path in sorted((WORKSPACE/'窗').glob('*.schem')):
        src=load_schematic(path);num=int(path.stem[1:] or 0);cid=f'window-source-{num:02d}'
        for value,count in src.exact_state_counts().items():
            if value in AIR_BLOCKS:continue
            y,z,x=map(int,np.argwhere(src.volume==src.palette[value])[0])
            state_index[technique(value)].append({'source':str(path.relative_to(WORKSPACE)),
                'state':value,'representative_xyz':[x,y,z],'count':count})
        converted=[];mapping=[]
        for value in src.id_to_state:
            normalized,reason=normalize(value,reg);converted.append(normalized)
            if reason:mapping.append({'original':value,'translated':normalized,'reason':reason})
        # Canonical palette deduplication after material translation.
        pal=list(dict.fromkeys(converted));remap=np.array([pal.index(s) for s in converted]);vol=remap[src.volume]
        dest=out/'windows'/cid;dest.mkdir(parents=True,exist_ok=True)
        write_schematic(dest/'component.schem',vol,pal,name=cid)
        read=load_schematic(dest/'component.schem');all_states.update(read.id_to_state)
        parts=defaultdict(list)
        for y,z,x in zip(*np.nonzero(src.nonair_mask())):
            v=src.id_to_state[src.volume[y,z,x]];label=technique(v)
            parts[label].append([int(x),int(y),int(z)])
        annotations={}
        roles={'wall_connections':'薄石窗颊/楣台的局部肢体，需结合位置解释',
               'pane_connections':'玻璃与窗内分隔','thin_planes':'薄窗扇、台板或遮挡片',
               'door_leaf_fragments':'借用门叶作为竖向细窗扇；不保证功能门配对',
               'gate_fragments':'门头或栏杆的细横竖构件','stair_shapes':'楣、拱或托件的切角轮廓'}
        for label,coords in parts.items():
            v=np.array(coords);annotations[label]={'role':roles.get(label,'需从上下文判断的支撑/装饰'),
                 'bbox_xyz':[v.min(0).tolist(),v.max(0).tolist()],'coordinates':coords,
                 'confidence':'material_and_position_classification; semantic inference'}
        record={'component_id':cid,'family':'window_assembly','source_schematic':str(path.relative_to(WORKSPACE)),
           'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
           'crop_bbox_xyz':[[0,0,0],[src.width-1,src.height-1,src.length-1]],
           'intended_view':'south/+z; back and axonometric_back are street side',
           'view_cone':{'preferred':['south','southeast','southwest'],'failure_views':['north unfinished backing']},
           'local_coordinates':'x/y/z; source unchanged; placement requires 180-degree conversion to canonical north',
           'anchors':{'base_centre':[src.width//2,0,src.length-1]},
           'connectors':{'left':[0,0,src.length-1],'right':[src.width-1,0,src.length-1]},
           'depth_layers':[{'z':z,'nonair':int(src.nonair_mask()[:,z,:].sum())} for z in range(src.length)],
           'exact_block_states':dict(src.exact_state_counts()),'subcomponents':annotations,
           'attachment':'source backing retained; host must reserve whole crop bounds',
           'occlusion':'rear solid blocks are construction backing, not exterior ornament',
           'scale_range':{'native_xyz':[src.width,src.height,src.length],'rescaling':'prohibited; compose or regenerate'},
           'lod':'near facade detail / mid-range frame silhouette','rotation':'state-aware quarter turns',
           'mirror':'state-aware x reflection','style_compatibility':['paris_haussmann'],
           'update_policy':'UNTESTED','evidence_status':'SOURCE_STATES_VERIFIED_SEMANTICS_INFERRED',
           'visual_interpretation':interpretations['windows'][str(num)],
           'translations':mapping,'dropped_block_entities':len(src.block_entities),
           'file_validation':read.validation(),'state_roundtrip':bool(np.array_equal(np.array(pal)[vol],np.array(read.id_to_state)[read.volume]))}
        if assets:
            record['card']=render_card(dest/'component.schem',dest/'views',assets,cid,outside='south')
            cards.append((cid,dest/'views/card.png'))
        dump_json(dest/'annotation.json',record);window_records.append(record)
        print('Window',cid,flush=True)
    derived=[];family_cards=[]
    for family in FAMILIES:
        for variant in range(3):
            # Every recipe carries actual technique evidence; relationship is
            # explicitly analogous, never falsely labelled an extracted macro.
            evidence_refs=[]
            preferred={
              'roof_slope':'stair_shapes','roof_junction':'stair_shapes','railing':'railing_connections',
              'mullion':'thin_planes','transom':'thin_planes','shutter':'thin_planes','awning':'thin_planes',
              'sill':'slab_halves','plinth':'slab_halves','string_course':'slab_halves','balcony_slab':'slab_halves',
              'cornice':'stair_shapes','arch':'stair_shapes','pediment':'stair_shapes','bracket':'stair_shapes',
              'corbel':'stair_shapes','door':'door_leaf_fragments','portal':'door_leaf_fragments',
              'shopfront':'pane_connections','window_recess':'pane_connections','glass_backing':'pane_connections',
              'dormer':'pane_connections','gutter':'stair_shapes','planter':'thin_planes',
              'downpipe':'railing_connections','basement_vent':'railing_connections',
              'sign_band':'solid_or_nonstateful','light_baffle':'solid_or_nonstateful','visible_interior':'solid_or_nonstateful'
            }.get(family,'wall_connections')
            entries=sorted(state_index.get(preferred,[]),key=lambda e:(
                0 if e['source'] in ('窗/窗27.schem','窗/窗26.schem','窗/窗17.schem') else
                1 if e['source'].endswith(('巴黎建筑素材2.schem','巴黎民居街区3.schem')) else 2,e['source']))
            selected=[];used_sources=set()
            for entry in entries:
                if entry['source'] not in used_sources:
                    selected.append(entry);used_sources.add(entry['source'])
                if len(selected)==3:break
            for entry in selected:
                evidence_refs.append({'source':entry['source'],'xyz':entry['representative_xyz'],
                                     'state':entry['state'],'relation':'technique_analogy_not_shape_copy'})
            comp=recipe(family,variant,evidence=evidence_refs)
            dest=out/'recipes'/comp.component_id;dest.mkdir(parents=True,exist_ok=True)
            coords=np.array([v[:3] for v in comp.voxels]);lo=coords.min(0);hi=coords.max(0)
            pal=['minecraft:air'];vol=np.zeros((hi[1]-lo[1]+3,hi[2]-lo[2]+3,hi[0]-lo[0]+3),np.int32)
            normvox=[]
            for x,y,z,value in comp.voxels:
                value,reason=normalize(value,reg)
                if reason:translations.append({'component':comp.component_id,'reason':reason})
                normvox.append([x,y,z,value])
                if value not in pal:pal.append(value)
                vol[y-lo[1]+1,z-lo[2]+1,x-lo[0]+1]=pal.index(value)
            comp.voxels=normvox;all_states.update(pal)
            write_schematic(dest/'component.schem',vol,pal,name=comp.component_id)
            record=asdict(comp);record['export_offset_xyz']=(1-lo).tolist()
            record['file_validation']=load_schematic(dest/'component.schem').validation()
            if assets:
                record['card']=render_card(dest/'component.schem',dest/'views',assets,comp.component_id)
                family_cards.append((comp.component_id,dest/'views/card.png'))
            dump_json(dest/'component.json',record);derived.append(record)
        print('Family',family,flush=True)
    # All production files are read back individually above; independently check
    # the union palette and Sponge codec with the JS registry tool.
    palette=sorted(all_states);probe=np.arange(len(palette),dtype=np.int32).reshape((1,1,-1))
    write_schematic(out/'registry_probe.schem',probe,palette,name='library registry probe')
    check=subprocess.run([NODE,str(ROOT/'tools/validate_schematic.cjs'),str(out/'registry_probe.schem'),str(out/'registry_validation.json')],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
    if check.returncode:raise RuntimeError(check.stdout+check.stderr)
    dump_json(out/'source_techniques.json',{'sources':evidence,'method':'all exact-state classes, representative contextual crops; semantics never inferred from state alone'})
    dump_json(out/'catalog.json',{'version':1,'families':FAMILIES,'windows':window_records,'recipes':derived,
           'counts':{'windows':len(window_records),'sources':len(evidence),'families':len(FAMILIES),'variants':len(derived)},
           'game_validation':'NOT_RUN','automatic_recipe_translation':translations})
    if assets:
        sheet(cards,out/'windows_atlas.png')
        for start in range(0,len(family_cards),36):sheet(family_cards[start:start+36],out/f'recipes_atlas_{start//36+1}.png')
        dump_json(out/'renderer_report.json',{'warnings':sorted(assets.warnings),'limitation':'entities and block entities are not rendered'})
        assets.jar.close()
    print('Library complete:',out,flush=True)

if __name__=='__main__':main()
