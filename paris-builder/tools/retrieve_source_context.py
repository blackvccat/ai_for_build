#!/usr/bin/env python3
"""Reconstruct any indexed source context without modifying its source."""
from pathlib import Path
import argparse,json,hashlib
import numpy as np
from paris_builder.schematic import load_schematic
from paris_builder.exporter import write_schematic,dump_json
from build_component_library import ROOT,registry,normalize,render_card
from paris_builder.preview3d import Assets,ensure_assets

def main():
    p=argparse.ArgumentParser();p.add_argument('context_id');p.add_argument('--output',type=Path,required=True)
    p.add_argument('--render',action='store_true');a=p.parse_args()
    index=ROOT/'knowledge/library-v1/exhaustive-contexts'
    selected=None
    with (index/'index.jsonl').open(encoding="utf-8") as f:
        for line in f:
            r=json.loads(line)
            if r['context_sha256']==a.context_id:selected=r;break
    if selected is None:raise ValueError('Unknown context SHA256')
    src=load_schematic(ROOT.parent/'巴黎建筑素材'/selected['source'])
    states=json.loads((index/'palette.json').read_text(encoding="utf-8"));ids={s:i for i,s in enumerate(states)}
    cx,cy,cz=selected['centre_xyz'];raw=np.full((5,5,5),ids['minecraft:air'],np.int32)
    for y in range(5):
        for z in range(5):
            for x in range(5):
                xx,yy,zz=cx+x-2,cy+y-2,cz+z-2
                if 0<=xx<src.width and 0<=yy<src.height and 0<=zz<src.length:
                    raw[y,z,x]=ids[src.id_to_state[src.volume[yy,zz,xx]]]
    if hashlib.sha256(raw.tobytes()).hexdigest()!=a.context_id:raise RuntimeError('Source context has changed')
    reg=registry();palette=[];mapping={};changes=[]
    for pid in np.unique(raw):
        value,reason=normalize(states[pid],reg)
        if value not in palette:palette.append(value)
        mapping[int(pid)]=palette.index(value)
        if reason:changes.append({'source':states[pid],'target':value,'reason':reason})
    volume=np.vectorize(mapping.__getitem__)(raw)
    a.output.mkdir(parents=True,exist_ok=True)
    write_schematic(a.output/'component.schem',volume,palette,name='source-context-'+a.context_id[:12])
    read=load_schematic(a.output/'component.schem')
    if not np.array_equal(np.array(palette)[volume],np.array(read.id_to_state)[read.volume]):raise RuntimeError('Roundtrip mismatch')
    dump_json(a.output/'evidence.json',{**selected,'source_hash_verified':True,'translations':changes,
        'roundtrip':'PASS','semantic_role':'NOT_YET_REVIEWED','game_validation':'NOT_RUN'})
    if a.render:render_card(a.output/'component.schem',a.output/'views',Assets(ensure_assets()),a.context_id[:12])
    print(a.output)

if __name__=='__main__':main()
