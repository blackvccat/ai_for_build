"""Style-independent scene, state transforms and facade topology.

Coordinates are x/y/z. A component's canonical outside is north (-z).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any
import hashlib
import json
import math
import numpy as np
from collections import Counter

DIRECTIONS = ('north', 'east', 'south', 'west')
VECTORS = {'north': (0,-1), 'east': (1,0), 'south': (0,1), 'west': (-1,0)}

def split_state(state):
    name, _, tail = state.partition('[')
    return name, dict(p.split('=',1) for p in tail.rstrip(']').split(',') if '=' in p)

def state(name, **props):
    name = name if ':' in name else 'minecraft:' + name
    return name + ('[' + ','.join(f'{k}={v}' for k,v in sorted(props.items())) + ']' if props else '')


def planar_connection(value, normal):
    """Freeze a pane/bar along a facade tangent, with every property explicit."""
    name, _ = split_state(value)
    along_x = normal[1] != 0
    return state(name, east=str(along_x).lower(), west=str(along_x).lower(),
                 north=str(not along_x).lower(), south=str(not along_x).lower(), waterlogged='false')

def transform_state(value, turns=0, mirror=False):
    """Reflect local x, then rotate clockwise about y; preserve complete properties."""
    name, props = split_state(value)
    def direction(d):
        if d not in DIRECTIONS:
            return d
        if mirror:
            d = {'east':'west','west':'east'}.get(d,d)
        return DIRECTIONS[(DIRECTIONS.index(d)+turns)%4]
    out = {}
    for key, val in props.items():
        k = direction(key)
        if key == 'facing':
            val = direction(val)
        if key == 'axis' and turns%2 and val in ('x','z'):
            val = 'z' if val=='x' else 'x'
        if mirror and key in ('shape','hinge','type'):
            val = {'inner_left':'inner_right','inner_right':'inner_left',
                   'outer_left':'outer_right','outer_right':'outer_left',
                   'left':'right','right':'left'}.get(val,val)
        if key == 'rotation':
            val = str(((-int(val) if mirror else int(val))+turns*4)%16)
        out[k] = val
    return state(name, **out)

def transform_point(x,y,z,turns=0,mirror=False):
    if mirror: x=-x
    for _ in range(turns%4): x,z=-z,x
    return x,y,z

def sensitive(value):
    name, props=split_state(value)
    # A candidate inventory, not a declaration that every property needs update
    # suppression. Suspended carpets also need testing despite having no props.
    return bool(props) or name.endswith(('_carpet','_torch'))

def state_category(value):
    name,props=split_state(value)
    for suffix,category in [('_wall','wall_connections'),('_pane','pane_connections'),
        ('iron_bars','railing_connections'),('_stairs','stair_shape'),('_slab','slab'),
        ('_fence_gate','fence_gate'),('_trapdoor','trapdoor'),('_door','door'),
        ('_carpet','suspended_candidate'),('_fence','fence_connections')]:
        if name.endswith(suffix):return category
    return 'other_state' if props else 'ordinary_block'

@dataclass
class StyleModel:
    style_id: str
    evidence: list
    invariants: list
    ranges: dict
    anti_patterns: list

@dataclass
class ComponentDefinition:
    component_id: str
    family: str
    variant: int
    voxels: list
    evidence: list
    annotation: dict = field(default_factory=dict)

    def transformed(self, turns=0, mirror=False):
        return [(*transform_point(x,y,z,turns,mirror),transform_state(s,turns,mirror))
                for x,y,z,s in self.voxels]

@dataclass
class Face:
    face_id: str
    start: tuple
    end: tuple
    role: str
    outward: tuple
    courtyard: bool=False

    @property
    def diagonal(self):
        return self.start[0]!=self.end[0] and self.start[1]!=self.end[1]

    @property
    def length(self):
        return max(abs(self.end[i]-self.start[i]) for i in (0,1))

    def point(self,u,y,d=0):
        t=u/max(1,self.length)
        return (round(self.start[0]+t*(self.end[0]-self.start[0])+d*self.outward[0]),
                y,round(self.start[1]+t*(self.end[1]-self.start[1])+d*self.outward[1]))

    @property
    def turns(self):
        # Oblique faces use staircase pairs; this value orients the thin model.
        nx,nz=self.outward
        return 1 if nx>0 else 3 if nx<0 else 2 if nz>0 else 0

@dataclass
class Footprint:
    outer: list
    courts: list=field(default_factory=list)

@dataclass
class MassingConcept:
    massing_seed: int
    style_id: str
    width: int
    depth: int
    chamfer: int
    court_width: int
    court_depth: int
    storeys: int
    bay_pitch: int
    roof_height: int
    entrance_fraction: float
    footprint_type: str
    roof_profile: str='steep_lower_shallow_crown'

@dataclass
class FaceGraph:
    outer: list
    courts: list
    faces: list

    def validate(self):
        issues=[]
        for loop_index,loop in enumerate([self.outer]+self.courts):
            if len(loop)<3: issues.append(f'loop {loop_index}: fewer than three edges')
            for a,b in zip(loop,loop[1:]+loop[:1]):
                if a==b: issues.append('zero length edge')
                dx,dz=abs(a[0]-b[0]),abs(a[1]-b[1])
                if dx and dz and dx!=dz: issues.append('edge must be cardinal or 45 degrees')
        return issues

    def mask(self,width,depth):
        z,x=np.mgrid[:depth,:width]
        def inside(poly):
            result=np.zeros((depth,width),dtype=bool)
            for a,b in zip(poly,poly[1:]+poly[:1]):
                x1,z1=a; x2,z2=b
                if z1!=z2:
                    result ^= ((z1>z+.01)!=(z2>z+.01)) & (x+.01<(x2-x1)*(z+.01-z1)/(z2-z1)+x1)
            return result
        result=inside(self.outer)
        for court in self.courts: result &= ~inside(court)
        return result

@dataclass
class AssemblyPlan:
    building_id: str
    seeds: dict
    placements: list=field(default_factory=list)
    collisions: list=field(default_factory=list)

@dataclass
class BuildManifest:
    building_id: str
    stage: str
    seeds: dict
    source_hashes: dict
    validations: dict
    game_acceptance: str='PENDING'

class Scene:
    def __init__(self,width,height,depth):
        self.volume=np.zeros((height,depth,width),np.int32)
        self.palette=['minecraft:air']; self.ids={self.palette[0]:0}
        self.owner={}; self.collisions=[]; self.placements=[]
        self.overwrite_counts=Counter(); self.overwrite_samples={}

    def put(self,x,y,z,value,owner='structure',replace=True):
        x,y,z=int(x),int(y),int(z)
        if not (0<=y<self.volume.shape[0] and 0<=z<self.volume.shape[1] and 0<=x<self.volume.shape[2]):
            raise ValueError(f'out of bounds {(x,y,z)} in {self.volume.shape}')
        if value not in self.ids:
            self.ids[value]=len(self.palette); self.palette.append(value)
        old=self.palette[self.volume[y,z,x]]
        if not replace and old!='minecraft:air' and old!=value:
            self.collisions.append({'xyz':[x,y,z],'existing':old,'requested':value,'owner':owner})
            return False
        old_owner=self.owner.get((x,y,z),'structure')
        if old!='minecraft:air' and old!=value and old_owner!=owner:
            key=old_owner+' -> '+owner
            self.overwrite_counts[key]+=1
            self.overwrite_samples.setdefault(key,[])
            if len(self.overwrite_samples[key])<3:self.overwrite_samples[key].append([x,y,z,old,value])
        self.volume[y,z,x]=self.ids[value]
        self.owner[(x,y,z)]=owner
        return True

    def box(self,x0,y0,z0,x1,y1,z1,value,owner='structure'):
        for y in range(y0,y1+1):
            for z in range(z0,z1+1):
                for x in range(x0,x1+1): self.put(x,y,z,value,owner)

    def voxel_unit(self, voxels, anchor, turns=0, unit_id='source-bay', extra=None):
        """Place a raw voxel unit (mined from a source bay) onto a face.

        `voxels` are (dx, dy, dz) offsets in a right-handed frame where canonical
        -z points out of the facade, so the same rotation used for components
        applies unchanged. Used by the source-bay vocabulary: the point of mining
        those units is that they get built, not just indexed.
        """
        placed = []
        for dx, dy, dz, value in voxels:
            x, y, z = transform_point(dx, dy, dz, turns)
            xyz = (int(x + anchor[0]), int(y + anchor[1]), int(z + anchor[2]))
            if self.put(*xyz, value, unit_id):
                placed.append(list(xyz))
        record = {'component_id': unit_id, 'anchor': list(anchor), 'turns': turns,
                  'voxels': placed, 'family': 'source_bay', 'source': 'mined'}
        if extra:
            record.update(extra)
        self.placements.append(record)
        return placed

    def component(self,component,anchor,turns=0,mirror=False,replace=True):
        placed=[];expected=[]
        for x,y,z,s in component.transformed(turns,mirror):
            xyz=(x+anchor[0],y+anchor[1],z+anchor[2])
            if self.put(*xyz,s,component.component_id,replace):
                placed.append(list(xyz));expected.append([*xyz,s])
        self.placements.append({'component_id':component.component_id,'anchor':list(anchor),
                                'turns':turns,'mirror':mirror,'voxels':placed,'expected_states':expected})

    def frozen_manifest(self):
        result=[]
        for pid,value in enumerate(self.palette):
            if sensitive(value):
                for y,z,x in zip(*np.where(self.volume==pid)):
                    result.append({'xyz':[int(x),int(y),int(z)],'state':value,
                                   'technical_category':state_category(value),
                                   'owner':self.owner.get((int(x),int(y),int(z)),'structure'),
                                   'update_policy':'UNTESTED_SUPPRESSED_PASTE_REQUIRED_FOR_REVIEW'})
        return result

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
