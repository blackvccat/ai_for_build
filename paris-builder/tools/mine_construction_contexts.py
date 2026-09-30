#!/usr/bin/env python3
"""Mine exact local construction contexts, retaining coordinate provenance.

This is a reproducible search index, not an assertion that material labels alone
constitute semantic architectural understanding.
"""
from pathlib import Path
from collections import Counter,defaultdict
import json
import hashlib
import numpy as np
from paris_builder.schematic import load_schematic,base_block,AIR_BLOCKS
from paris_builder.architecture import split_state,digest
from paris_builder.exporter import dump_json,write_schematic
from build_component_library import technique,registry,normalize,ROOT,WORKSPACE

def main():
    out=ROOT/'knowledge/library-v1/contexts';out.mkdir(parents=True,exist_ok=True)
    reg=registry();clusters={};sources=[];exclusions=[]
    for path in sorted((WORKSPACE/'巴黎建筑素材').glob('*.schem')):
        s=load_schematic(path);normal=[normalize(v,reg)[0] for v in s.id_to_state]
        counts=s.exact_state_counts();source_records=[]
        for value,count in sorted(counts.items()):
            if base_block(value) in AIR_BLOCKS:continue
            family=technique(value);name,props=split_state(value)
            if not props:
                exclusions.append({'source':path.name,'state':value,'count':count,
                   'reason':'solid/nonstateful material retained in source inventory; contextual geometry only, not a standalone frozen-state technique'})
                continue
            locations=np.argwhere(s.volume==s.palette[value])
            # First, median and last occurrences often sample different facade
            # heights/ends while bounding library size. Unexamined coordinates
            # are counted honestly, rather than silently declared duplicates.
            indices=sorted(set([0,len(locations)//2,len(locations)-1]))
            for index in indices:
                y,z,x=map(int,locations[index]);lo=[max(0,x-2),max(0,y-2),max(0,z-2)]
                hi=[min(s.width,x+3),min(s.height,y+3),min(s.length,z+3)]
                arr=s.volume[lo[1]:hi[1],lo[2]:hi[2],lo[0]:hi[0]]
                exact=np.asarray(s.id_to_state)[arr]
                signature=digest({'shape':arr.shape,'states':exact.ravel().tolist()})
                cid='CTX-'+signature[:16]
                occurrence={'source':str(path.relative_to(WORKSPACE)),'centre_xyz':[x,y,z],
                  'crop_bbox_xyz_inclusive':[lo,[v-1 for v in hi]],'central_state':value}
                if cid not in clusters:
                    palette=list(dict.fromkeys(normal[int(i)] for i in np.unique(arr)))
                    lut={v:i for i,v in enumerate(palette)}
                    vol=np.asarray([lut[normal[int(i)]] for i in arr.ravel()],np.int32).reshape(arr.shape)
                    dest=out/(cid+'.schem');write_schematic(dest,vol,palette,name=cid)
                    clusters[cid]={'context_id':cid,'exact_source_context_sha256':signature,'technique':family,
                       'source_palette':sorted(set(exact.ravel().tolist())),
                       'translated_palette':palette,'source_occurrences':[],
                       'disposition':'indexed contextual evidence; macro role requires source facade relation',
                       'game_test':'NOT_RUN','file_validation':load_schematic(dest).validation()}
                clusters[cid]['source_occurrences'].append(occurrence)
                source_records.append(cid)
            if len(locations)>len(indices):exclusions.append({'source':path.name,'state':value,
                'count':len(locations)-len(indices),'reason':'additional state occurrences not context-sampled; not claimed to be semantic duplicates'})
        sources.append({'source':path.name,'indexed_contexts':len(set(source_records))})
        print('Contexts',path.name,len(set(source_records)),flush=True)
    dump_json(out/'index.json',{'clusters':list(clusters.values()),'sources':sources,'exclusions':exclusions,
       'status':'EVIDENCE_SEARCH_INDEX','semantic_exhaustiveness':'NOT_PROVEN',
       'deduplication':'exact 5x5x5 source-state and shape identity only; no false equivalence across different contexts'})
    print('Unique exact contexts',len(clusters),flush=True)

if __name__=='__main__':main()
