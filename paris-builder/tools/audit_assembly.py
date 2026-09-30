#!/usr/bin/env python3
"""Audit component retention and bounded nonuniform source-patch reuse."""
from pathlib import Path
import argparse,json,hashlib
import numpy as np
from paris_builder.schematic import load_schematic
from paris_builder.exporter import dump_json
ROOT=Path(__file__).resolve().parents[1]

def hashes(s,size=8,stride=4):
    lut=np.array([hashlib.sha256(v.encode()).hexdigest()[:16] for v in s.id_to_state])
    out={}
    for y in range(0,s.height-size+1,stride):
        for z in range(0,s.length-size+1,stride):
            for x in range(0,s.width-size+1,stride):
                patch=s.volume[y:y+size,z:z+size,x:x+size]
                unique,counts=np.unique(patch,return_counts=True)
                if len(unique)<5 or counts.max()>patch.size*.85:continue
                key=hashlib.sha256(lut[patch].tobytes()).hexdigest()
                out.setdefault(key,[x,y,z])
    return out

def main():
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path);a=p.parse_args()
    s=load_schematic(a.directory/'PAR-002.schem')
    plan=json.loads((a.directory/'assembly_plan.json').read_text(encoding="utf-8"));retention=[]
    for i,c in enumerate(plan['placements']):
        expected=c.get('expected_states',[])
        retained=sum(s.id_to_state[s.volume[y,z,x]]==v for x,y,z,v in expected)
        retention.append({'placement':i,'component_id':c['component_id'],'anchor':c['anchor'],
                          'expected':len(expected),'retained':retained,
                          'status':'REVIEW_FULL_OVERWRITE' if expected and not retained else 'RECORDED'})
    targets=hashes(s);sources=[];matches=[]
    for path in sorted((ROOT.parent/'巴黎建筑素材').glob('*.schem')):
        h=hashes(load_schematic(path));sources.append({'file':path.name,'sampled_unique_patches':len(h)})
        matches.extend({'source':path.name,'source_xyz':h[k],'target_xyz':targets[k]} for k in h.keys()&targets.keys())
    dump_json(a.directory/'assembly_retention.json',{'placements':retention,'fully_overwritten':sum(r['status']=='REVIEW_FULL_OVERWRITE' for r in retention),
          'overwrite_counts':plan.get('overwrite_audit',{}).get('counts',{}),
          'boundary':'Ordered assembly overwrites are recorded. Partial retention does not prove correct visibility.'})
    dump_json(a.directory/'originality_audit.json',{'method':'Exact-state heterogeneous 8x8x8 patches, stride4, axis aligned',
          'target_patches':len(targets),'sources':sources,'matches':matches,
          'status':'SAMPLED_NO_MATCH' if not matches else 'REVIEW_MATCHES',
          'limitations':'Not exhaustive: rotated, offset, smaller and transformed regions excluded. Generator instantiates derived recipes instead of loading source voxel regions.'})
    print('placements',len(retention),'full overwrite',sum(r['status']=='REVIEW_FULL_OVERWRITE' for r in retention),'patch matches',len(matches))

if __name__=='__main__':main()
