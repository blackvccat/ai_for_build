#!/usr/bin/env python3
"""Reproducible PAR-002 competition, tiered assembly and acceptance delivery."""
from pathlib import Path
from collections import Counter
import argparse
import json
import hashlib
import shutil
import subprocess
import tempfile
import numpy as np
from paris_builder.production import propose, build
from paris_builder.architecture import Scene, digest
from paris_builder.exporter import dump_json, write_schematic
from paris_builder.schematic import load_schematic
from paris_builder.geometry import inspect_geometry
from paris_builder.preview3d import render_previews
from paris_builder.executor import state_lab as build_state_lab
from paris_builder.fonts import node_binary

ROOT=Path(__file__).resolve().parents[1]
NODE=node_binary()
SEEDS=[6101,6211,6317,6421,6521]

def require_review(base, name, key, value):
    path=base/name
    if not path.exists():raise RuntimeError('Missing visual stage review: '+str(path))
    review=json.loads(path.read_text(encoding="utf-8"))
    if review.get(key)!=value:raise RuntimeError('Selection differs from reviewed stage: '+str(path))
    if name=='framework_review.json':
        selected=next(r for r in review['reviews'] if r['seed']==value)
        if sum(selected['scores'])<80 or min(selected['scores'])<14:raise RuntimeError('Framework below visual gate')
    return review

def verify(path,scene,out):
    read=load_schematic(path);rep=read.validation()
    rep['checks']['exact_states_roundtrip']=bool(np.array_equal(np.array(scene.palette)[scene.volume],np.array(read.id_to_state)[read.volume]))
    rep['status']='PASS' if all(rep['checks'].values()) else 'FAIL'
    dump_json(out/'validation.json',rep)
    geometry=inspect_geometry(read);dump_json(out/'geometry_validation.json',geometry)
    r=subprocess.run([NODE,str(ROOT/'tools/validate_schematic.cjs'),str(path),str(out/'independent_validation.json')],capture_output=True,text=True,encoding='utf-8',errors='replace',cwd=ROOT)
    if r.returncode or rep['status']!='PASS' or geometry['status']!='PASS':
        raise RuntimeError(f'{path}: {r.stdout} {r.stderr} geometry={geometry}')
    frozen=scene.frozen_manifest()
    exact=all(read.id_to_state[read.volume[e['xyz'][1],e['xyz'][2],e['xyz'][0]]]==e['state'] for e in frozen)
    dump_json(out/'frozen_state_validation.json',{'status':'PASS' if exact else 'FAIL','count':len(frozen),'states':frozen,
         'game_updates':'NOT_RUN','note':'Candidate sensitive states; count is not proof of suppression dependency.'})
    dump_json(out/'materials.json',dict(read.base_block_counts()))
    dump_json(out/'block_states.json',dict(read.exact_state_counts()))
    return read

def save_build(c,out,stage,scheme,render=True,orbit=True,size=1000):
    out.mkdir(parents=True,exist_ok=True)
    facade_seed=c.get('facade_seed',4409+scheme);detail_seed=c.get('detail_seed',5519)
    scene,meta=build(c,facade_seed=facade_seed,detail_seed=detail_seed,stage=stage,scheme=scheme)
    path=out/('PAR-002.schem' if stage else 'framework.schem')
    write_schematic(path,scene.volume,scene.palette,name=f'PAR-002 stage {stage} scheme {scheme}')
    read=verify(path,scene,out)
    repeat,_=build(c,facade_seed=facade_seed,detail_seed=detail_seed,stage=stage,scheme=scheme)
    deterministic=np.array_equal(np.array(scene.palette)[scene.volume],np.array(repeat.palette)[repeat.volume])
    if not deterministic:raise RuntimeError('non-deterministic scene')
    with tempfile.TemporaryDirectory() as tmp:
        replica=Path(tmp)/'repeat.schem'
        write_schematic(replica,repeat.volume,repeat.palette,name=f'PAR-002 stage {stage} scheme {scheme}')
        byte_identical=replica.read_bytes()==path.read_bytes()
    if not byte_identical:raise RuntimeError('non-deterministic schematic bytes')
    dump_json(out/'assembly_plan.json',meta)
    previews=render_previews(path,out/'previews',max_size=size,orbit=orbit) if render else {}
    # Preview paths are stored relative to the package root so a package rebuilt
    # on another machine or user account stays readable.
    previews={key:(str(Path(value).resolve().relative_to(ROOT)) if Path(value).is_absolute() else str(value))
              for key,value in previews.items()}
    manifest={'building_id':'PAR-002','stage':stage,'seeds':meta['seeds'],'scheme':scheme,
              'voxel_state_hash':read.voxel_state_hash(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
              'deterministic_state_replay':deterministic,'repeat_byte_identical':byte_identical,
              'dimensions_whl':[read.width,read.height,read.length],
              'source_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'src/paris_builder').glob('*.py')},
              'face_count':len(meta['face_graph']['faces']),'component_ids':meta['component_ids'],'previews':previews,
              'release_status':'PENDING_VISUAL_REVIEW','game_acceptance':'PENDING'}
    manifest['style_model_sha256']=hashlib.sha256((ROOT/'knowledge/styles/paris_haussmann_v0.1.json').read_bytes()).hexdigest()
    manifest['component_catalog_sha256']=hashlib.sha256((ROOT/'knowledge/library-v1/catalog.json').read_bytes()).hexdigest()
    dump_json(out/'concept.json',c)
    dump_json(out/'manifest.json',manifest)
    print('BUILT',out,flush=True)
    return scene,meta

def state_lab(scene,meta,out):
    """Thin wrapper over the shared state-lab builder used by the model executor."""
    return build_state_lab(scene,out)

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['frameworks','facades','tier','deliver'])
    p.add_argument('--seed',type=int,default=6421);p.add_argument('--scheme',type=int,default=1)
    p.add_argument('--stage',type=int,default=3);p.add_argument('--run',default='PAR-002-v0.1')
    p.add_argument('--skip-render',action='store_true');p.add_argument('--size',type=int,default=1000)
    a=p.parse_args();base=ROOT/'runs'/a.run
    if a.mode=='frameworks':
        concepts=[propose(seed) for seed in SEEDS]
        for i,c in enumerate(concepts):
            for other in concepts[:i]:
                if sum(c[k]!=other[k] for k in c if k!='massing_seed')<3:raise RuntimeError('insufficient variation')
            save_build(c,base/'frameworks'/str(c['massing_seed']),0,0,not a.skip_render,size=a.size)
        dump_json(base/'framework_competition.json',{'concepts':concepts,'visual_review':'SEE framework_review.json (separate stage gate)'})
    elif a.mode=='facades':
        require_review(base,'framework_review.json','selected_seed',a.seed)
        for scheme in range(3):save_build(propose(a.seed),base/'facades'/str(scheme),1,scheme,not a.skip_render,size=a.size)
    elif a.mode=='tier':
        require_review(base,'framework_review.json','selected_seed',a.seed)
        require_review(base,'facade_review.json','selected_scheme',a.scheme)
        save_build(propose(a.seed),base/f'tier-{a.stage}',a.stage,a.scheme,not a.skip_render,size=a.size)
    else:
        require_review(base,'framework_review.json','selected_seed',a.seed)
        require_review(base,'facade_review.json','selected_scheme',a.scheme)
        require_review(base,'detail_review.json','ready_for_delivery',True)
        scene,meta=save_build(propose(a.seed),base/'delivery',3,a.scheme,not a.skip_render,size=a.size)
        count=state_lab(scene,meta,base/'delivery');print('State lab plots:',count,flush=True)

if __name__=='__main__':main()
