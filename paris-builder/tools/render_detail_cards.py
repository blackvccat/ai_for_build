#!/usr/bin/env python3
from pathlib import Path
import argparse,json
import numpy as np
from paris_builder.schematic import load_schematic
from paris_builder.exporter import write_schematic,dump_json
from paris_builder.architecture import Face
from paris_builder.preview3d import Assets,ensure_assets,_mesh,_render
from PIL import Image,ImageDraw

def main():
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path);a=p.parse_args()
    src=load_schematic(a.directory/'PAR-002.schem');meta=json.loads((a.directory/'assembly_plan.json').read_text(encoding="utf-8"))
    assets=Assets(ensure_assets());out=a.directory/'detail-cards';out.mkdir(exist_ok=True);records=[]
    faces=meta['face_graph']['faces']
    for fid,label in [('F00','street-window'),('F01','diagonal-corner'),('F05','courtyard-window')]:
        record=next(f for f in faces if f['face_id']==fid)
        f=Face(**{k:record[k] for k in ('face_id','start','end','role','outward','courtyard')})
        o=next(o for o in meta['openings'] if o['face']==fid and o['floor']==1)
        pts=np.array([f.point(u,y,d) for u in (o['left']-3,o['left']+o['width']+3)
             for y in (o['bottom']-2,o['bottom']+o['height']+3) for d in (-5,4)])
        lo=np.maximum(pts.min(0),0);hi=np.minimum(pts.max(0),[src.width-1,src.height-1,src.length-1])
        x,y,z=lo;xx,yy,zz=hi
        dest=out/label;dest.mkdir(exist_ok=True)
        write_schematic(dest/'crop.schem',src.volume[y:yy+1,z:zz+1,x:xx+1],src.id_to_state,name=label)
        mesh=_mesh(load_schematic(dest/'crop.schem'),assets)
        nx,nz=f.outward;tx,tz=-nz,nx
        views=[('front',(nx,.05,nz)),('oblique',(nx+tx*.7,.5,nz+tz*.7)),('side',(tx,.1,tz)),('top',(0,1,0))]
        sheet=Image.new('RGB',(1400,1160),'#e5ebef')
        for i,(name,direction) in enumerate(views):
            target=dest/(name+'.png');_render(mesh,assets,direction,name,target,650)
            im=Image.open(target).convert('RGB');im.thumbnail((690,565))
            sheet.paste(im,((i%2)*700,(i//2)*580))
        sheet.save(dest/'card.png');records.append({'label':label,'source_bbox_xyz':[lo.tolist(),hi.tolist()],'face':fid})
    dump_json(out/'index.json',records)
    print('Detail cards complete',len(records))

if __name__=='__main__':main()
