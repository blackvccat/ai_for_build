#!/usr/bin/env python3
"""Exhaustive local-context inventory; never equate local coverage with semantics."""
from pathlib import Path
from collections import Counter
import hashlib,json
import numpy as np
from paris_builder.schematic import load_schematic
from paris_builder.exporter import dump_json
from build_component_library import technique
ROOT=Path(__file__).resolve().parents[1]

def main():
    paths=sorted((ROOT.parent/'巴黎建筑素材').glob('*.schem'))
    sources=[(p,load_schematic(p)) for p in paths]
    states=sorted({'minecraft:air'}|{s for _,src in sources for s in src.id_to_state})
    state_ids={s:i for i,s in enumerate(states)};air=state_ids['minecraft:air']
    offsets=np.array([(y,z,x) for y in range(-2,3) for z in range(-2,3) for x in range(-2,3)])
    unique={};totals=[];homogeneous=0
    for path,src in sources:
        table=np.array([state_ids[v] for v in src.id_to_state],dtype=np.int32)
        volume=np.pad(table[src.volume],2,constant_values=air)
        coords=np.argwhere(src.nonair_mask());eligible=0
        for start in range(0,len(coords),2048):
            centres=coords[start:start+2048];q=centres[:,None,:]+offsets[None,:,:]+2
            neighborhoods=volume[q[:,:,0],q[:,:,1],q[:,:,2]]
            for point,patch in zip(centres,neighborhoods):
                y,z,x=map(int,point);center=src.id_to_state[src.volume[y,z,x]]
                if np.all(patch==patch[62]) and '[' not in center:
                    homogeneous+=1;continue
                eligible+=1;key=hashlib.sha256(patch.tobytes()).hexdigest()
                if key not in unique:
                    unique[key]={'context_sha256':key,'source':path.name,'centre_xyz':[x,y,z],
                         'crop_bbox_xyz':[[x-2,y-2,z-2],[x+2,y+2,z+2]],'centre_state':center,
                         'technical_class':technique(center),'occurrences':0,'source_counts':{},
                         'production_disposition':'SOURCE_EVIDENCE_ONLY',
                         'exclusion_reason':'Local context is retained for retrieval, not promoted to a production component without architectural-role, view-cone and game evidence.'}
                r=unique[key];r['occurrences']+=1;r['source_counts'][path.name]=r['source_counts'].get(path.name,0)+1
        totals.append({'source':path.name,'nonair_positions_scanned':len(coords),'retained_occurrences':eligible})
        print(path.name,len(coords),'positions, cumulative unique',len(unique),flush=True)
    out=ROOT/'knowledge/library-v1/exhaustive-contexts';out.mkdir(exist_ok=True)
    with (out/'index.jsonl').open('w',encoding="utf-8") as f:
        for key in sorted(unique):f.write(json.dumps(unique[key],ensure_ascii=False)+'\n')
    dump_json(out/'palette.json',states)
    dump_json(out/'coverage.json',{'status':'COMPLETE_LOCAL_POSITION_SCAN','neighborhood_size':5,
         'sources':totals,'unique_contexts':len(unique),'homogeneous_material_interiors_excluded':homogeneous,
         'exclusion_policy':'Only uniform stateless 5-cubes omitted; repetitions clustered with exact multiplicity; source/crop coordinates preserve each unique combination.',
         'technical_classes':dict(Counter(r['technical_class'] for r in unique.values())),
         'semantic_exhaustiveness':'NOT_PROVEN: local complete scan does not discover every multi-component architectural assembly',
         'boundary_padding':'Coordinates outside source bounds are air; crop bounds may be negative',
         'game_tests':'NOT_RUN'})
    print('Complete',len(unique),'unique local contexts',flush=True)

if __name__=='__main__':main()
