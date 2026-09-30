#!/usr/bin/env python3
"""Validate every production component with the independent JS reader."""
from pathlib import Path
import json
import subprocess
from collections import Counter
from build_component_library import ROOT,NODE
from paris_builder.exporter import dump_json
from paris_builder.architecture import transform_state

def main():
    root=ROOT/'knowledge/library-v1';catalog=json.loads((root/'catalog.json').read_text(encoding="utf-8"))
    files=sorted((root/'windows').glob('*/component.schem'))+sorted((root/'recipes').glob('*/component.schem'))
    checks=[]
    for i,path in enumerate(files):
        report=path.parent/'independent_validation.json'
        result=subprocess.run([NODE,str(ROOT/'tools/validate_schematic.cjs'),str(path),str(report)],capture_output=True,text=True,encoding='utf-8',errors='replace')
        if result.returncode:raise RuntimeError(str(path)+'\n'+result.stdout+result.stderr)
        checks.append({'component':path.parent.name,'status':'PASS','report':str(report.relative_to(ROOT))})
        if i%20==0:print('independent components',i+1,'/',len(files),flush=True)
    families=Counter(r['family'] for r in catalog['recipes'])
    issues=[]
    for family,n in families.items():
        if n<3:issues.append('missing variants: '+family)
        values={json.dumps(r['voxels'],sort_keys=True) for r in catalog['recipes'] if r['family']==family}
        if len(values)<3:issues.append('duplicate variants: '+family)
    for record in catalog['recipes']:
        for *_,value in record['voxels']:
            if transform_state(transform_state(value,mirror=True),mirror=True)!=value:issues.append('mirror mismatch '+record['component_id'])
    for record in catalog['windows']:
        if not record.get('visual_interpretation'):issues.append('missing interpretation '+record['component_id'])
    report={'status':'PASS' if not issues else 'FAIL','production_files':len(files),'checks':checks,'issues':issues,
            'family_counts':dict(families),'game_tests':'NOT_RUN',
            'semantic_scope':'43 source windows interpreted; 135 derived recipes; local source contexts are a search index, not semantic completeness proof'}
    dump_json(root/'production_audit.json',report)
    if issues:raise RuntimeError(issues)
    print('Production component file audit PASS',len(files),flush=True)

if __name__=='__main__':main()
