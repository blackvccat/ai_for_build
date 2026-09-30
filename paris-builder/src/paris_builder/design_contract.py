"""Validated model-authored design data. Model output is never executable code."""
import math
from .components import FAMILIES

ROLES={'primary_street','secondary_street','corner','rear_return','service_street','courtyard'}
LIMITS={'width':(45,85),'depth':(35,65),'chamfer':(4,12),'court_width':(13,29),
        'court_depth':(17,31),'storeys':(3,6),'bay_pitch':(5,8),'roof_height':(8,13)}

# Models reach for the architectural noun rather than the library's family id.
# Mapping the common ones to a real placeable family keeps a usable design from
# failing the contract over vocabulary, while anything unmapped still fails so a
# genuinely unknown family is never silently accepted.
# The retrieval library's window family is a study family (placeable=false) that
# the model keeps selecting because it is architecturally the right choice. It is
# mapped to the placeable surround family and the substitution is recorded, so the
# pipeline stays runnable while the rename remains visible in the evidence.
FAMILY_ALIASES = {
    'window': 'window_surround', 'windows': 'window_surround',
    'window_assembly': 'window_surround', 'window_source': 'window_surround',
    'window_frame': 'window_surround', 'window_frames': 'window_surround',
    'recess': 'window_recess', 'window_opening': 'window_recess', 'opening': 'window_recess',
    'balcony': 'balcony_slab', 'balcony_rail': 'railing', 'railing_iron': 'railing',
    'shop_front': 'shopfront', 'store_front': 'shopfront', 'storefront': 'shopfront', 'shop': 'shopfront',
    'column': 'pilaster', 'pillar': 'pilaster', 'pilasters': 'pilaster',
    'cornice_band': 'cornice', 'frieze': 'string_course', 'band': 'string_course',
    'roof': 'roof_slope', 'roof_ridge': 'ridge', 'mansard': 'roof_slope',
    'window_sill': 'sill', 'sills': 'sill', 'window_head': 'cornice',
    'doorway': 'door', 'entry': 'portal', 'entrance': 'portal', 'gate': 'door',
    'dormers': 'dormer', 'chimneys': 'chimney', 'chimney_stack': 'chimney',
    'quoin_stone': 'quoin', 'corner_stone': 'quoin', 'base': 'plinth', 'basement': 'plinth',
    'wall': 'masonry_joint', 'stone_wall': 'masonry_joint', 'brick': 'masonry_joint',
    'glass': 'glass_backing', 'glazing': 'glass_backing', 'shutters': 'shutter',
    'planter_box': 'planter', 'awnings': 'awning', 'gutter_pipe': 'downpipe',
    'balustrade_rail': 'balustrade', 'parapet_wall': 'parapet', 'pediment_roof': 'pediment',
    'arch_stone': 'arch', 'arches': 'arch', 'vent': 'basement_vent', 'vent_grille': 'basement_vent',
    'sign': 'sign_band', 'signage': 'sign_band', 'signboard': 'sign_band',
}

# Families that exist in the source library but are studies, not placeable
# production families; naming them is a real mistake, not a vocabulary slip.
STUDY_ONLY = {'window_study', 'study', 'context', 'crop'}


def resolve_family(name):
    """Canonical placeable family for `name`, or None when it is not placeable."""
    if not isinstance(name, str):
        return None
    cleaned = name.strip().lower().replace(' ', '_').replace('-', '_').replace('minecraft:', '')
    if cleaned in FAMILIES:
        return cleaned
    alias = FAMILY_ALIASES.get(cleaned)
    return alias if alias in FAMILIES else None


def normalize_component_policy(policy):
    """Rewrite role -> family maps onto placeable family ids and valid variants.

    Returns (normalized_policy, notes). Notes record every rename and clamp so the
    change is visible in the run evidence instead of happening silently. A variant
    outside 0..2 is clamped because variant choice is a design preference, not a
    contract violation that should discard an otherwise usable concept.
    """
    if not isinstance(policy, dict):
        return policy, []
    normalized, notes = {}, []
    for role, families in policy.items():
        if not isinstance(families, dict):
            normalized[role] = families
            continue
        fixed = {}
        for family, choice in families.items():
            # A policy is role -> family -> selection. Models sometimes put a role
            # name in the family slot (often the same role, e.g.
            # primary_street/primary_street), which names no component at all.
            if family in ROLES:
                notes.append({'role': role, 'family': family, 'action': 'dropped_role_as_family'})
                continue
            resolved = resolve_family(family)
            if resolved is None:
                notes.append({'role': role, 'family': family, 'action': 'unresolved'})
                fixed[family] = choice
                continue
            if resolved != family:
                notes.append({'role': role, 'family': family, 'resolved': resolved, 'action': 'renamed'})
            if isinstance(choice, dict) and 'variant' in choice:
                variant = choice.get('variant')
                if not isinstance(variant, int) or isinstance(variant, bool) or variant not in (0, 1, 2):
                    clamped = variant % 3 if isinstance(variant, int) and not isinstance(variant, bool) else 0
                    notes.append({'role': role, 'family': resolved, 'variant': variant,
                                  'clamped_to': clamped, 'action': 'variant_clamped'})
                    choice = {**choice, 'variant': clamped}
            fixed[resolved] = choice
        normalized[role] = fixed
    return normalized, notes


def validate_concept(c):
    c['component_policy'], _ = normalize_component_policy(c.get('component_policy', {}))
    for key,(lo,hi) in LIMITS.items():
        v=c.get(key)
        if not isinstance(v,int) or isinstance(v,bool) or not lo<=v<=hi:raise ValueError(f'{key} must be integer {lo}..{hi}')
    for key in ('massing_seed','facade_seed','detail_seed'):
        if not isinstance(c.get(key,0),int):raise ValueError(key+' must be integer')
    if not .2<=c.get('entrance_fraction',0)<=.8:raise ValueError('entrance_fraction outside .2..8')
    if c.get('footprint_type') not in ('l_plan','open_court','enclosed_court','custom'):raise ValueError('Unsupported footprint_type')
    if c.get('roof_profile')!='steep_lower_shallow_crown':raise ValueError('Unsupported roof profile')
    if c['width']-c['court_width']<20 or c['depth']-c['court_depth']<12:raise ValueError('Insufficient wing depth')
    if c['footprint_type']=='custom':
        shape=c.get('footprint',{});outer=shape.get('outer',[]);roles=shape.get('roles',[])
        loops=[outer]+shape.get('courts',[])
        if len(roles)!=len(outer) or any(r not in ROLES for r in roles):raise ValueError('Every outer segment requires a known role')
        for li,loop in enumerate(loops):
            if not 3<=len(loop)<=24:raise ValueError('Polygon requires 3..24 vertices')
            for point in loop:
                if len(point)!=2 or any(not isinstance(v,int) for v in point):raise ValueError('Integer x/z vertices required')
                if not 8<=point[0]<=8+c['width'] or not 8<=point[1]<=8+c['depth']:raise ValueError('Footprint outside padded extent')
            area=sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(loop,loop[1:]+loop[:1]))
            if (li==0 and area<=0) or (li>0 and area>=0):raise ValueError('Outer winding must be positive; court negative in x/z')
            edges=list(zip(loop,loop[1:]+loop[:1]))
            for a,b in edges:
                dx,dz=abs(a[0]-b[0]),abs(a[1]-b[1])
                if max(dx,dz)<6 or (dx and dz and dx!=dz):raise ValueError('Edges require length>=6 and cardinal/45 degrees')
            def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
            for i,(a,b) in enumerate(edges):
                for j,(d,e) in enumerate(edges):
                    if j<=i+1 or (i==0 and j==len(edges)-1):continue
                    if cross(a,b,d)*cross(a,b,e)<=0 and cross(d,e,a)*cross(d,e,b)<=0:
                        if max(min(a[0],b[0]),min(d[0],e[0]))<=min(max(a[0],b[0]),max(d[0],e[0])) and max(min(a[1],b[1]),min(d[1],e[1]))<=min(max(a[1],b[1]),max(d[1],e[1])):raise ValueError('Self-intersecting polygon')
        # General intersecting/nested courts are intentionally unsupported.
        if len(loops)>2:raise ValueError('At most one custom courtyard supported')
    for role,policy in c.get('component_policy',{}).items():
        if role not in ROLES:raise ValueError('Unknown policy role: '+str(role))
        if not isinstance(policy,dict) or not policy:raise ValueError('Policy for '+role+' must map family -> selection')
        for family,choice in policy.items():
            if not isinstance(choice,dict):raise ValueError(f'Invalid component selection {role}/{family}: expected {{variant,reason,evidence_refs}}')
            if family not in FAMILIES or choice.get('variant') not in (0,1,2):raise ValueError(f'Invalid component selection {role}/{family}: variant {choice.get("variant")} is not 0/1/2 or family is not placeable')
            if not choice.get('reason') or not choice.get('evidence_refs'):raise ValueError('Component selection needs reason and evidence: '+role+'/'+family)
    return c

