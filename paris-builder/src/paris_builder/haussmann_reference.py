"""Single party-wall apartment, translating audited source techniques into a new plan.

The source window states are retained, not normalized into functional doors. Room
planning is new design inference; it is never attributed to the source schematics.
"""
import hashlib
import json
from pathlib import Path

import numpy as np

from .architecture import Scene, state, transform_state

ROOT = Path(__file__).resolve().parents[2]
AIR = 'minecraft:air'
STONE = 'minecraft:smooth_sandstone'
DRESS = 'minecraft:cut_sandstone'
BASE = 'minecraft:cut_sandstone'
PLINTH = 'minecraft:polished_andesite'
WOOD = 'minecraft:spruce_planks'
ROOF = 'minecraft:deepslate_tiles'
ROOF_UPPER = 'minecraft:polished_deepslate'
ROOF_RIDGE = 'minecraft:polished_deepslate'
ROOF_BREAK = 'minecraft:deepslate_bricks'
PARTY_STONE = 'minecraft:sandstone'
GLASS = 'minecraft:glass'
#: Shop bays get their own vocabulary: a dark timber sign band and frame over the
#: glazing, a dark stall riser under it, and a darker pane so the commercial base is
#: separated from the limestone above. Sharing the residential surround is what made the
#: ground floor read as a row of oversized windows instead of a commercial base.
SIGN_BAND = 'minecraft:dark_oak_planks'
SHOP_TIMBER = 'minecraft:dark_oak_planks'
SHOP_GLASS = 'minecraft:gray_stained_glass'
DORMER_GLASS = 'minecraft:light_gray_stained_glass'


def stair(name, facing, half='bottom', shape='straight'):
    return state(name, facing=facing, half=half, shape=shape, waterlogged='false')


def slab(name, kind='top'):
    return state(name, type=kind, waterlogged='false')


def bars(along='x'):
    return state('iron_bars', east=str(along == 'x').lower(), west=str(along == 'x').lower(),
                 north=str(along == 'z').lower(), south=str(along == 'z').lower(), waterlogged='false')


def diagonal_bars():
    # A 45-degree iron-bar run needs all four connection axes true; an x-only
    # state leaves the diagonal rail visually broken at the pan-coupé.
    return state('iron_bars', east='true', west='true', north='true', south='true',
                 waterlogged='false')


def evidence():
    ids = ('s3-window-bay', 's3-upper-balcony', 's3-cornice', 's3-dormer',
           's3-chimney', 's3-roof-section', 'b2-base', 'b2-pilaster', 'street3-facade-4')
    rows = []
    for ident in ids:
        folder = ROOT / 'knowledge/library-v3/reference-techniques' / ident
        raw = json.loads((folder / 'record.json').read_text(encoding='utf-8'))
        if hashlib.sha256((folder / 'detail.schem').read_bytes()).hexdigest() != raw['schematic_sha256']:
            raise ValueError('Source sample changed: ' + ident)
        rows.append({'id': 'v3:' + ident, 'source': raw['source'], 'source_sha256': raw['source_sha256'],
                     'bbox': raw['source_bbox_xyz_half_open'], 'record_sha256': hashlib.sha256(
                         (folder / 'record.json').read_bytes()).hexdigest(),
                     'clean_origin_source_xyz': raw['clean_origin_source_xyz'],
                     'schematic_sha256': raw['schematic_sha256'],
                     'role': 'technique translation; new building coordinates, not whole-crop placement'})
    window = json.loads((ROOT / 'knowledge/library-v3/reference-techniques/s3-window-bay/record.json').read_text(encoding='utf-8'))
    doors = sorted(s for s in window['inventory']['exact_states'] if s.startswith('minecraft:iron_door['))
    assert len(doors) == 2 and all('half=lower' in s for s in doors)
    return rows, doors


def build(plan, tier=3):
    if tier not in range(4):
        raise ValueError('Unknown refinement tier')
    if plan.form == 'corner_house':
        return build_corner(plan, tier)
    # Preserve the non-corner adapter palette and behavior.
    BASE = 'minecraft:polished_andesite'
    GLASS = 'minecraft:light_gray_stained_glass'
    refs, door_states = evidence()
    x0, z0 = 6, 6
    x1, z1 = x0 + plan.width - 1, z0 + plan.depth - 1
    heights = [7, 7] + [6] * (plan.storeys - 2)
    floors = [1]
    for h in heights:
        floors.append(floors[-1] + h)
    top = floors[-1]
    roof_h = plan.roof_height or 7
    scene = Scene(x1 + 7, top + roof_h + 7, z1 + 8)
    put, box = scene.put, scene.box
    pitch = plan.bay_pitch or 5
    count = max(3, (plan.width - 4 - 2) // pitch + 1)
    start = x0 + (plan.width - ((count - 1) * pitch + 2)) // 2
    bays = [start + i * pitch for i in range(count)]
    entry_index = round((plan.entrance_fraction if plan.entrance_fraction is not None else .5) * (count - 1))
    entrance = bays[entry_index]
    cx = x0 + plan.width // 2
    openings, decorative, stairs = [], [], []
    # Ground and every storey have a real floor; street/rear walls are two cells deep.
    for y in floors:
        box(x0, y, z0, x1, y, z1, WOOD, 'floor')
    box(x0, 0, z0, x1, 0, z1, BASE, 'foundation')
    for a, b in ((z0, z0 + 1), (z1 - 1, z1)):
        box(x0, 1, a, x1, top, b, STONE, 'facade')
    for x in (x0, x1):
        box(x, 1, z0, x, top + roof_h, z1, 'minecraft:stone_bricks', 'party-wall')
    # Keep a steep lower slope and a shallow crown reaching the ridge, even at height 5.
    half_depth = (plan.depth - 1) // 2
    break_rise = max(3, round(roof_h * .65))
    break_distance = max(1, (break_rise - 1 + 1) // 2)
    def roof_rise(distance):
        if distance <= break_distance:
            return min(break_rise, 1 + 2 * distance)
        return break_rise + round((roof_h - break_rise) * (distance - break_distance) /
                                 max(1, half_depth - break_distance))
    profiles = [roof_rise(min(dz, plan.depth - 1 - dz)) for dz in range(plan.depth)]
    for dz in range(plan.depth):
        rise = profiles[dz]
        adjacent = min(profiles[max(0, dz - 1)], profiles[min(plan.depth - 1, dz + 1)])
        for x in range(x0 + 1, x1):
            box(x, top + min(rise, adjacent + 1), z0 + dz,
                x, top + rise, z0 + dz, ROOF, 'roof-shell')
        # Party gables follow the actual roof, with no oversized rectangular side towers.
        for x in (x0, x1):
            box(x, top + 1, z0 + dz, x, top + rise, z0 + dz, STONE, 'party-gable')
            box(x, top + rise + 1, z0 + dz, x, top + roof_h, z0 + dz, AIR, 'gable-trim')
            put(x, top + rise + 1, z0 + dz, slab('stone_brick_slab', 'bottom'), 'party-cap')
    balcony_levels = [1, max(2, plan.storeys - 2)]
    if plan.scheme == 'plain_terrace': balcony_levels = [1]
    for rear in (False, True):
        face, normal = (z1, 1) if rear else (z0, -1)
        for li, floor in enumerate(floors[:-1]):
            for bi, bx in enumerate(bays):
                bottom = floor + 1
                kind = 'window'
                if li == 0:
                    kind = 'door' if bi == entry_index else ('window' if rear else 'shop')
                # A separate cafe entrance at the leftmost bay, while the residence stays independent.
                if not rear and li == 0 and bi == (0 if entry_index != 0 else count - 1): kind = 'cafe_door'
                span = min(pitch - 1, x1 - bx) if kind == 'shop' else 2
                h = 6 if kind == 'shop' else (5 if li <= 1 else (3 if li == plan.storeys - 1 else 4))
                h = min(h, floors[li + 1] - bottom)
                box(bx, bottom, min(face, face - normal), bx + span - 1, bottom + h - 1,
                    max(face, face - normal), AIR, 'opening')
                glazing = bottom
                if kind == 'shop' and tier >= 2:
                    box(bx, bottom, min(face, face - normal), bx + span - 1, bottom,
                        max(face, face - normal), BASE, 'stall-riser')
                    glazing += 1
                for xx in range(bx, bx + span):
                    if kind not in ('door', 'cafe_door'):
                        box(xx, glazing, face - normal, xx, bottom + h - 1, face - normal, GLASS, 'glazing')
                    elif tier >= 2:
                        for dy, half in enumerate(('lower', 'upper')):
                            put(xx, bottom + dy, face, state('dark_oak_door', facing='south' if rear else 'north',
                                half=half, hinge='left' if xx == bx else 'right', open='false', powered='false'), 'functional-door')
                        box(xx, bottom + 2, face - normal, xx, bottom + h - 1, face - normal, GLASS, 'door-transom')
                openings.append({'face': 'rear' if rear else 'street', 'floor': li, 'x': bx,
                    'y': bottom, 'z': face, 'width': span, 'height': h, 'kind': kind})
                if tier >= 1 and kind == 'shop':
                    for xx in (bx - 1, bx + span):
                        box(xx, bottom, face, xx, bottom + h - 1, face, BASE, 'shop-pier')
                    box(bx - 1, bottom + h, face, bx + span, bottom + h, face,
                        SIGN_BAND if tier >= 2 else BASE, 'shop-lintel')
                    if tier >= 2 and span >= 3:
                        box(bx + span // 2, glazing, face, bx + span // 2, bottom + h - 1,
                            face, BASE, 'shop-mullion')
                elif tier >= 1:
                    for xx in (bx - 1, bx + 2):
                        for yy in range(bottom, bottom + h):
                            value = STONE if rear else state('sandstone_wall', east='tall', north='tall',
                                south='tall', west='tall', up='false', waterlogged='false')
                            put(xx, yy, face, value, 'window-jamb')
                    for xx in range(bx - 1, bx + 3):
                        put(xx, bottom + h, face, slab('sandstone_slab'), 'window-head')
                        if kind not in ('door', 'cafe_door'):
                            put(xx, floor, face + normal, slab('sandstone_slab'), 'window-sill')
                if tier >= 2 and not rear and li > 0:
                    for dx, source_state in enumerate(door_states):
                        value = transform_state(source_state, turns=2)
                        for yy in range(bottom, bottom + h):
                            put(bx + dx, yy, face, value, 'source-thin-window')
                            decorative.append({'xyz': [bx + dx, yy, face], 'state': value,
                                'source_id': 'v3:s3-window-bay', 'transformation': 'rotate_y_180; retain half=lower'})
                if tier >= 3 and li > 0 and (rear or li not in balcony_levels):
                    for xx in (bx, bx + 1): put(xx, bottom, face + normal, bars(), 'window-guard')
        if not rear:
            for li in balcony_levels:
                y = floors[li]
                box(x0 + 1, y, z0 - 3, x1 - 1, y, z0 - 1,
                    slab('sandstone_slab') if tier else STONE, 'balcony-plate')
                for bx in bays:
                    put(bx, y - 1, z0 - 1, stair('sandstone_stairs', 'south', 'top'), 'balcony-bracket')
                if tier >= 2:
                    for x in range(x0 + 1, x1): put(x, y + 1, z0 - 3, bars(), 'balcony-rail')
                    for x in (x0 + 1, x1 - 1):
                        for z in (z0 - 2, z0 - 1): put(x, y + 1, z, bars('z'), 'balcony-return')
            if tier >= 1:
                for y, depth in ((top - 1, 1), (top, 2), (top + 1, 1)):
                    box(x0, y, z0 - depth, x1, y, z0 - 1, slab('sandstone_slab') if y == top + 1 else DRESS, 'cornice')
                for li in range(1, plan.storeys):
                    if li not in balcony_levels:
                        box(x0 + 1, floors[li], z0, x1 - 1, floors[li], z0, slab('sandstone_slab'), 'storey-course')
                if plan.scheme == 'palace_front':
                    # Competing composition: a stronger centre and entrance crown.
                    # Kept separate from the restrained apartment proposal.
                    for x in (entrance - 2, entrance + 3):
                        box(x, 2, z0 - 1, x, top - 2, z0 - 1, DRESS, 'central-pilaster')
                    for offset in range(3):
                        box(entrance - 2 + offset, floors[1] - 1 + offset, z0 - 2,
                            entrance + 3 - offset, floors[1] - 1 + offset, z0 - 2,
                            slab('sandstone_slab'), 'entry-pediment')
            if tier >= 3:
                # Rustication affects only solid piers, never painted across openings.
                for x in range(x0, x1 + 1):
                    if any(o['x'] - 1 <= x <= o['x'] + o['width'] for o in openings
                           if o['face'] == 'street' and o['floor'] == 0): continue
                    for y in range(2, floors[1]):
                        put(x, y, z0, BASE if y % 2 else 'minecraft:andesite', 'rustication')
        elif tier >= 1:
            for y in floors[1:]: box(x0, y, z1, x1, y, z1, DRESS, 'rear-course')
    # Glazed dormers sit in front of the lower slope and are open to the attic.
    for rear in (False, True):
        front = z1 - 1 if rear else z0 + 1
        inward = -1 if rear else 1
        cap = min(5, roof_h - 1)
        dormer_depth = next(d for d in range(1, half_depth + 1) if profiles[d] >= cap)
        for bx in bays:
            for dx in (-1, 0, 1, 2):
                for d in range(dormer_depth):
                    z = front + d * inward
                    for dy in range(1, cap):
                        put(bx + dx, top + dy, z, STONE if dx in (-1, 2) else AIR, 'dormer-shell')
                    put(bx + dx, top + cap, z, ROOF, 'dormer-cap')
            for xx in (bx, bx + 1):
                for yy in range(top + 1, top + cap - 1): put(xx, yy, front, GLASS, 'dormer-glass')
                put(xx, top + cap - 1, front, slab('sandstone_slab') if tier else STONE, 'dormer-head')
            if tier >= 2:
                for xx in range(bx - 1, bx + 3):
                    put(xx, top + cap, front - inward, slab('sandstone_slab'), 'dormer-drip')
    # Chimney stacks are on the party lines, with supported clay flues.
    for x in (x0 + 1, x1 - 1):
        for z in (z0 + 8, z1 - 8):
            roof_y = top + profiles[z - z0]
            box(x, roof_y, z, x, top + roof_h + 2, z + 1, 'minecraft:bricks', 'chimney')
            if tier >= 2:
                for zz in (z, z + 1):
                    put(x, top + roof_h + 3, zz, state('anvil', facing='north'), 'chimney-cap')
                    if tier >= 3: put(x, top + roof_h + 4, zz, 'minecraft:flower_pot', 'chimney-pot')
    # Stairs and the central circulation strip are explicit, with slab openings/headroom.
    stair_x, stair_z = cx, z0 + 10
    for lo, hi in zip(floors, floors[1:]):
        rise = hi - lo
        box(stair_x, hi, stair_z - 1, stair_x + 1, hi, stair_z + rise - 2, AIR, 'stairwell-opening')
        for step in range(rise):
            z, y = stair_z + step, lo + step + 1
            for x in (stair_x, stair_x + 1):
                if y > lo + 1: put(x, y - 1, z, WOOD, 'stair-stringer')
                put(x, y, z, stair('spruce_stairs', 'south'), 'stair-flight')
                stairs.append([x, y, z])
        if tier >= 3:
            for z in range(stair_z, stair_z + rise - 1):
                put(stair_x + 2, hi + 1, z, bars('z'), 'stairwell-guard')
    # Two apartments per floor around a shared entrance/stair corridor. Internal
    # doorways are deliberately open passages: no fake functional-door claims.
    rooms = []
    for li, y in enumerate(floors[:-1]):
        ceiling = floors[li + 1]
        if tier >= 2:
            for x in (cx - 3, cx + 4):
                box(x, y + 1, z0 + 2, x, ceiling - 1, z1 - 2, 'minecraft:calcite', 'interior-partition')
                for z in (z0 + 6, z1 - 6):
                    box(x, y + 1, z, x, y + 3, z + 1, AIR, 'interior-passage')
            # Entrance may move in competing frames: its foyer always reaches the spine.
            if li == 0:
                box(min(entrance, cx - 3), y + 1, z0 + 2, max(entrance + 1, cx + 4), y + 3, z0 + 5, AIR, 'foyer-cross-passage')
            for xa, xb in ((x0 + 2, cx - 4), (cx + 5, x1 - 2)):
                mid_z = z0 + plan.depth // 2
                box(xa, y + 1, mid_z, xb, ceiling - 1, mid_z, 'minecraft:calcite', 'room-partition')
                box(xa + 1, y + 1, mid_z, xa + 2, y + 3, mid_z, AIR, 'room-passage')
                rooms.append({'floor': li, 'bounds': [xa, y + 1, z0 + 2, xb, ceiling - 1, z1 - 2],
                    'use': 'cafe/residential service shell' if li == 0 else 'front living / rear bedroom shell'})
                if tier >= 3:
                    put(xa + 1, y + 1, z0 + 4, 'minecraft:bookshelf', 'interior-furniture')
                    put(xa + 2, y + 1, z0 + 4, stair('spruce_stairs', 'south'), 'interior-seat')
                    put(xa + 1, y + 1, z1 - 4, 'minecraft:crafting_table', 'interior-table')
            if tier >= 3:
                for z in (z0 + 7, z1 - 5):
                    put(cx - 1, y, z, 'minecraft:sea_lantern', 'corridor-light')
    if tier >= 3:
        for x in (x0 + 1, x1 - 1):
            for y in range(2, top + 1):
                put(x, y, z1 + 1, state('iron_chain', axis='y', waterlogged='false'), 'rain-leader')
        # Street lamps flank the residential portal, below the first balcony.
        for x in (entrance - 1, entrance + 2):
            put(x, 5, z0 - 1, state('lantern', hanging='true', waterlogged='false'), 'entrance-lamp')
            put(x, 6, z0 - 1, slab('sandstone_slab'), 'lamp-bracket')
    techniques = {} if tier == 0 else {'window_surround': len(openings), 'cornice': 1,
        'source_window_state': len(decorative), 'balcony_band': len(balcony_levels), 'dormer': len(bays) * 2}
    manifest = {'plan': plan.describe(), 'profile': 'reference_haussmann', 'techniques': techniques,
        'structure': {'form': plan.form, 'width': plan.width, 'depth': plan.depth, 'storeys': plan.storeys,
            'floors_y': floors, 'top': top, 'roof_height': roof_h, 'attic': 'additional roof space',
            'roof_section': {'axis': 'z', 'rises_from_eave': profiles,
                             'slope_break_distance': break_distance, 'slope_break_rise': break_rise,
                             'scope': 'generated geometry; style acceptance requires visual comparison'}},
        'walls': [{'name': name, 'role': role, 'openings': sum(o['face'] == name for o in openings)}
                  for name, role in [('street', 'primary'), ('rear', 'courtyard'), ('party_west', 'party'), ('party_east', 'party')]],
        'bay_x': bays, 'entrance_x': entrance, 'balcony_floor_indices': balcony_levels,
        'openings': openings, 'decorative_doors': decorative, 'stair_cells': stairs,
        'rooms': rooms, 'source_techniques': refs, 'cells': int(np.count_nonzero(scene.volume)),
        'scene_whd': [scene.volume.shape[2], scene.volume.shape[0], scene.volume.shape[1]],
        'limitations': ['Interior room shells and basic furniture only; no complete kitchens/bathrooms.',
            'Rear court is contextual open space outside this single building export.',
            'Source decorative door halves need suppressed updates; game behavior NOT_RUN.'],
        'game_acceptance': 'PENDING'}
    return scene, manifest


# --- corner form: two adjacent street faces --------------------------------
def _corner_break(roof_h, ridge_run):
    '''Plan position and rise of the mansard break.

    The lower slope is the steep mansard face that carries the dormers; the
    upper slope is the shallow cap that reaches the ridge.  In voxel terms
    the lower face is nearly a vertical band: it rises about twice as fast as
    it runs inward, while the upper slope is visibly shallower and longer.
    '''
    roof_h = max(4, int(roof_h))
    ridge_run = max(4, int(ridge_run))
    # Reserve most of the roof height for the steep lower band and keep the
    # upper stage shallow enough to read as a separate roof plane rather than
    # as a continued staircase.
    lower_run = max(2, min(ridge_run // 2, max(2, roof_h // 3)))
    lower_run = max(1, min(ridge_run - 1, lower_run))
    lower_rise = max(lower_run + 2, min(roof_h - 1, lower_run * 2))
    return lower_run, lower_rise


def _corner_slope(d, roof_h, ridge_run):
    '''Rise above `top` at distance `d` from an eave: an explicit two-stage mansard.

    The lower stage starts at a single low eave course and climbs steeply to
    the break; the upper stage leaves the break shelf shallowly and reaches
    `roof_h` only at `ridge_run`, so the crest is a line rather than a broad
    plateau.  Starting the eave at one course is what makes the steep lower
    slope readable in elevation: the older profile already stood five courses
    tall at its outer edge, which is why orbit views read the crown as a flat
    box instead of a mansard.
    '''
    roof_h = max(4, int(roof_h))
    ridge_run = max(4, int(ridge_run))
    d = max(0.0, min(float(d), float(ridge_run)))
    lower_run, lower_rise = _corner_break(roof_h, ridge_run)
    if d <= lower_run:
        # Steep lower stage: one low eave course, then a fast climb to the
        # break.  Interpolating the rise across the run keeps the slope
        # monotonic and avoids the old five-course vertical curb at d=0.
        if lower_run <= 0:
            return lower_rise
        step = 1 + (lower_rise - 1) * (d / lower_run)
        return max(1, min(lower_rise, int(round(step))))
    if d >= ridge_run:
        return roof_h
    upper_run = max(1, ridge_run - lower_run)
    upper_rise = max(0, roof_h - lower_rise)
    # Shallow upper stage: one readable step at a time toward the ridge.
    step = int(round(upper_rise * (d - lower_run) / upper_run))
    return max(lower_rise, min(roof_h, lower_rise + step))


def _corner_rise(dx, dz, wid, dep, roof_h, chamfer=0):
    '''Height of a four-slope hip mansard over the rectangular corner footprint.

    Height is the minimum of the mansard profile measured from every eave:
    north, south, east, west, and (when present) the true pan-coupé diagonal.
    Measuring from each eave separately keeps the shallow upper slope resolving
    into a continuous ridge line.  On even-width plans the far side of the
    central pair is compressed by one cell, so the crest is one cell wide
    instead of a two-cell plateau.
    '''
    x_run = max(1, (wid - 1) // 2)
    z_run = max(2, (dep - 1) // 2)
    ridge_run = min(x_run, z_run)
    ridge_dx = (wid - 1) // 2
    x_dist = min(dx, wid - 1 - dx)
    if wid % 2 == 0 and dx > ridge_dx:
        east_span = max(1, wid - ridge_dx - 2)
        x_dist = ((wid - 1 - dx) * max(0, ridge_run - 1) + east_span // 2) // east_span
    z_dist = min(dz, dep - 1 - dz)
    diag_dist = 10 ** 9
    if chamfer > 0:
        # Signed perpendicular distance from the true pan-coupé diagonal:
        # (wid - 1 - dx) + dz == chamfer.  Only the segment between the
        # two street hinges contributes an eave; beyond it the ordinary
        # north/east slopes must take over.
        f = (wid - 1 - dx) + dz - chamfer
        if f >= 0:
            hinge = wid - 1 - chamfer
            along = (dx + dz) - hinge
            # The diagonal eave has chamfer+1 integer cells; their along
            # values run from -chamfer to +chamfer.  The old 0..2*chamfer
            # test dropped the north half of the pan-coupé and let the
            # ordinary north/east hips take over midway along the cut.
            if -chamfer <= along <= chamfer:
                diag_dist = f / 1.41421356
    return _corner_slope(min(x_dist, z_dist, diag_dist), roof_h, ridge_run)


def _corner_source_details(scene, faces, openings, refs):
    """Translate complete source state motifs into each residential reveal.

    The source samples face south. Rotate their coordinates and their states together:
    north is two clockwise turns and east is three. The thin door leaves stay recessed,
    with glazing behind, rather than closing the street plane. Source-only wall limbs
    and top inner stair ends replace the full-block outer surround, so these states have
    a visible architectural job. This is a translation of sampled motifs, not a claim
    that the entire source crop fits this building.
    """
    from .technique_library import load_detail
    samples = {ident: load_detail(ident) for ident in ('v3:s3-window-bay', 'v3:street3-facade-4')}
    references = {row['id']: row for row in refs}
    audit, decorative = [], []

    def sampled(ident, source_local, target, turns, role, face, opening_id):
        read, reference = samples[ident], references[ident]
        sx, sy, sz = source_local
        original = read.id_to_state[int(read.volume[sy, sz, sx])]
        value = transform_state(original, turns=turns)
        scene.put(*target, value, 'source:' + role)
        origin = reference['clean_origin_source_xyz']
        row = {'source_id': ident, 'source_path': reference['source'],
               'source_sha256': reference['source_sha256'],
               'sample_sha256': reference['schematic_sha256'],
               'source_xyz': [origin[0] + sx, origin[1] + sy, origin[2] + sz],
               'source_local_xyz': list(source_local), 'original_state': original,
               'transformed_state': value, 'target_xyz': list(target),
               'turns': turns, 'mirror': False, 'role': role, 'face': face['name'],
               'storey': openings[opening_id]['floor'], 'opening_id': opening_id}
        audit.append(row)
        if role == 'thin_door_window':
            decorative.append({'xyz': list(target), 'state': value, 'source_id': ident,
                               'source_xyz': row['source_xyz'], 'opening_id': opening_id,
                               'transformation': 'rotate_y_%d; retain decorative half=lower' % (turns * 90)})

    for face in faces:
        at = face['at']
        turns = 2 if face['along'] == 'x' else 3
        for opening_id, opening in enumerate(openings):
            if opening['face'] != face['name'] or opening['floor'] == 0:
                continue
            bu, bottom, height = opening['u'], opening['y'], opening['height']
            # The full source window has two opposing rows of thin leaves. At this
            # building's smaller reveal use the outer leaf row and retain clear glass
            # behind it; the recess remains open at d=0. Repeat only in height.
            for du, source_x in ((0, 2), (1, 1)):
                for dy in range(height):
                    sampled('v3:s3-window-bay', (source_x, 1 + min(dy, 3), 3),
                            at(bu + du, bottom + dy, 1), turns, 'thin_door_window', face, opening_id)
                    scene.put(*at(bu + du, bottom + dy, 2), GLASS, 'source-window-backing')
            # One-sided wall limbs make a slim reveal edge. These are genuine frozen
            # source states, and their single tall limb points toward the opening.
            # Segment four supplies the same one-limb construction in sandstone,
            # which keeps the reveal inside this building's limestone palette.
            for u, source_x in ((bu - 1, 13), (bu + 2, 4)):
                for dy in range(height):
                    sampled('v3:street3-facade-4', (source_x, 10, 7),
                            at(u, bottom + dy, -1), turns, 'single_arm_wall', face, opening_id)
            # The four-cell source head is a continuous top-half soffit with inner
            # ends. Leave the independently designed triangular rakes at d=-2 intact.
            for du in range(4):
                sampled('v3:s3-window-bay', (3 - du, 5, 3),
                        at(bu - 1 + du, bottom + height, -1), turns,
                        'shaped_stair', face, opening_id)

    for row in audit:
        x, y, z = row['target_xyz']
        row['survives'] = scene.palette[int(scene.volume[y, z, x])] == row['transformed_state']
    return audit, decorative


def build_corner(plan, tier=3):
    """An immeuble d'angle: two adjacent street faces meeting at the corner.

    north (z_min) faces street A and east (x_max) faces street B; the two walls that meet
    the neighbouring plots - west (x_min) and south (z_max) - are party walls and carry
    no openings at all. Both street faces receive the full composition (shop base, ordered
    bays, storey courses, cornice, balcony bands, dormers), and the crown is a four-slope
    roof so that each street keeps an eave instead of turning into a gable. This is the
    plot shape an ordinary continuous street wall cannot express.
    """
    if tier not in range(4):
        raise ValueError('Unknown refinement tier')
    refs, door_states = evidence()
    from .technique_library import registry as _technique_registry
    try:
        library_registry = _technique_registry()
        dispatch_count = len(library_registry)
    except Exception:
        library_registry = {}
        dispatch_count = 0
    stamp_audit = []
    x0, z0 = 6, 6
    x1, z1 = x0 + plan.width - 1, z0 + plan.depth - 1
    if plan.storeys <= 1:
        floor_roles = ['ground']
        heights = [7]
    elif plan.storeys == 2:
        floor_roles = ['ground', 'entresol']
        heights = [7, 5]
    elif plan.storeys == 3:
        floor_roles = ['ground', 'entresol', 'noble']
        heights = [7, 5, 8]
    elif plan.storeys == 4:
        floor_roles = ['ground', 'entresol', 'noble', 'attic']
        heights = [7, 5, 8, 4]
    else:
        floor_roles = (['ground', 'entresol', 'noble'] +
                       ['standard'] * (plan.storeys - 4) + ['attic'])
        # Base and mezzanine carry the heavy stone mass; the entresol must be
        # tall enough to carry a vertical 2x4 light with a one-course head
        # band, so it gets six cells rather than five. The noble floor stays
        # tall, the standard floors step down, and the attic keeps a five-cell
        # rise so its window head clears the cornice corbel row.
        heights = [8, 6, 7] + [6] * (plan.storeys - 4) + [5]
    floors = [1]
    for h in heights:
        floors.append(floors[-1] + h)
    top = floors[-1]
    roof_h = plan.roof_height or 9

    def opening_height(role, kind):
        if kind == 'shop':
            # The ground storey is eight cells high; a five-cell square shop
            # opening reads as a punched hole.  Six cells gives the commercial
            # base the tall Haussmann proportion while keeping the stall riser
            # and fascia in the stone base.
            return 6
        if role == 'ground':
            return 5
        if role == 'entresol':
            # The entresol is a heavy stone storey but its lights are still
            # vertical: a 2x4 opening leaves a one-course head band under a
            # six-cell storey and matches the standard-floor window rhythm.
            return 4
        if role == 'noble':
            # The noble light stays the tallest, but yields one course so a
            # pediment can occupy the head band under the seven-cell storey.
            return 5
        if role == 'attic':
            # The attic light is set up under the crown and keeps a plain
            # dressed head; a pediment there would collide with the cornice.
            return 3
        # Standard residential floors: a 2x4 opening is still vertical and
        # leaves the head band the pediment family needs.
        return 4

    ridge_run = max(2, min(max(1, (plan.width - 1) // 2),
                           max(2, (plan.depth - 1) // 2)))
    break_run, break_rise = _corner_break(roof_h, ridge_run)
    scene = Scene(x1 + 10, top + roof_h + 7, z1 + 10)
    put, box = scene.put, scene.box
    pitch = plan.bay_pitch or 6
    cx = x0 + plan.width // 2

    #: The pan coupé. The corner is cut on the diagonal so the two streets meet on a
    #: third, narrower face — the defining feature of the reference corner building, and
    #: its absence is what the review kept rejecting as "a right-angle corner".
    # The pan coupé is framework geometry, not a switch: chamfer=0 (or an unset
    # value) means "use the scaled default", never "remove the cut" -- degrading
    # the confirmed corner to a right angle is prohibited by the brief.
    default_chamfer = max(4, min(6, min(plan.width, plan.depth) // 4))
    chamfer = plan.chamfer if plan.chamfer else default_chamfer
    chamfer = max(4, min(6, chamfer))

    def cut_corner(x, z):
        """True inside the triangle the pan coupé removes at the shared corner."""
        return (x1 - x) + (z - z0) < chamfer

    def bay_axis(span, from_end):
        """Bays counted from the shared pan-coupé corner column.

        The first bay starts two cells in from the shared pan-coupé corner
        column, leaving a full corner column plus a one-cell reveal on both
        streets, then every following bay steps by the same pitch.  Both
        streets therefore share one anchor: the north face counts back from
        x1-chamfer, the east face counts forward from z0+chamfer.
        """
        lo, hi = span
        bays = []
        offset = 2
        if from_end:
            corner = hi
            while corner - offset - 1 >= lo:
                bays.append(corner - offset - 1)
                offset += pitch
        else:
            corner = lo
            while corner + offset + 1 <= hi:
                bays.append(corner + offset)
                offset += pitch
        return sorted(bays)

    def make_face(name, origin, length, horizontal, entry, along):
        """One street plane. `d` runs inward from the outer skin; a negative d is outside."""
        if horizontal:
            # `d` runs inward from the outer skin: on the north face the building goes
            # towards +z, so the skin is z0 and d=1 is z0+1. A negative d is the street.
            def at(u, y, d): return (u, y, z0 + d)
            def cub(ua, ub, ya, yb, da, db): return (ua, ya, z0 + min(da, db), ub, yb, z0 + max(da, db))
            span, door = (x0 + 1, x1 - chamfer), 'north'
        else:
            def at(u, y, d): return (x1 - d, y, u)
            def cub(ua, ub, ya, yb, da, db): return (x1 - max(da, db), ya, ua, x1 - min(da, db), yb, ub)
            span, door = (z0 + chamfer, z1 - 1), 'east'
        return {'name': name, 'at': at, 'cub': cub, 'door': door, 'along': along, 'span': span,
                'bays': bay_axis(span, horizontal), 'length': length, 'entry': entry}

    faces = [make_face('street_north', x0, plan.width, True, True, 'x'),
             make_face('street_east', z0, plan.depth, False, False, 'z')]

    def bay_clear(face, u):
        """True when a two-cell residential light clears the pan-coupé.

        The shared corner column and the first reveal are reserved, so the
        clear test measures only the opening itself.  Wide shop bays are
        capped separately below; no opening cell may lie inside the cut
        triangle or on the true diagonal wall.
        """
        _c0, c1 = face['span']
        room = c1 - u + 1
        if room < 2:
            return False
        span = 2
        lo, hi = u, u + span - 1
        if face['along'] == 'x':
            cells = ((x, z) for x in range(lo, hi + 1) for z in (z0, z0 + 1))
        else:
            cells = ((x, z) for z in range(lo, hi + 1) for x in (x1 - 1, x1))
        for (x, z) in cells:
            if cut_corner(x, z) or (x1 - x) + (z - z0) == chamfer:
                return False
        return True

    for face in faces:
        face['bays'] = [u for u in face['bays'] if bay_clear(face, u)]
    # Both streets share one bay pitch and one pan-coupé anchor, not one bay
    # count: the two frontages are the plot width and the plot depth, so the
    # longer street legitimately carries more bays at the same pitch.  The
    # earlier min() truncation dropped the east face's farthest bay and left
    # z=30..34 as an unarticulated blank run on a primary street, which is a
    # rhythm failure rather than a rhythm lock.  bay_axis already starts both
    # faces at offset 1 from the shared corner, so the grid stays anchored
    # with per-face counts.
    for face in faces:
        face['bays'] = sorted(face['bays'])

    def ground_band(face):
        """Continuous commercial base for one street face.

        The shopfronts are anchored on the upper-storey bay axes, then extended
        across the remaining frontage until only single-cell stone piers remain.
        The residential portal keeps one dressed jamb cell on each side, and the
        pan-coupé hinge cell is reserved so the shared corner column stays
        visible.  Upper storeys keep the pitch-anchored two-cell bays; only the
        ground floor reads as one continuous shop band.
        """
        c0, c1 = face['span']
        if face['along'] == 'x':
            band_lo, band_hi = c0, c1 - 1
        else:
            band_lo, band_hi = c0 + 1, c1
        door_bu = None
        if face['entry'] and face['bays']:
            fraction = plan.entrance_fraction if plan.entrance_fraction is not None else .5
            door_bu = face['bays'][round(fraction * (len(face['bays']) - 1))]
        intervals = []
        for bu in face['bays']:
            if bu == door_bu:
                continue
            lo = max(band_lo, bu)
            hi = min(band_hi, bu + pitch - 2)
            if lo <= hi:
                intervals.append([lo, hi, 'shop'])
        if door_bu is not None:
            intervals.append([door_bu, min(door_bu + 1, band_hi), 'door'])
        intervals.sort()
        for i in range(len(intervals) - 1):
            current, following = intervals[i], intervals[i + 1]
            if following[0] - current[1] - 1 >= 2:
                if current[2] == 'shop':
                    current[1] = following[0] - 2
                elif following[2] == 'shop':
                    following[0] = current[1] + 2
        if intervals and intervals[-1][2] == 'shop' and intervals[-1][1] < band_hi:
            intervals[-1][1] = band_hi
        return [(lo, hi - lo + 1, kind) for lo, hi, kind in intervals]

    ground_layout = {face['name']: ground_band(face) for face in faces}

    openings, decorative, stairs = [], [], []
    pediments = 0
    triangular_pediments = 0
    # Floor plates and foundation, minus the corner the pan coupé takes away.
    for y in floors:
        for x in range(x0, x1 + 1):
            for z in range(z0, z1 + 1):
                if not cut_corner(x, z):
                    put(x, y, z, WOOD, 'floor')
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            if not cut_corner(x, z):
                put(x, 0, z, BASE, 'foundation')
    # Party walls first, then the two street skins, so the angle itself reads as street.
    # They stop just above the eave instead of rising through the roof: the shared wall
    # stays blind, while the four roof slopes remain visible and meet the cornice line.
    box(x0, 1, z0, x0, top + 2, z1, PARTY_STONE, 'party-west')
    box(x0, 1, z1, x1 - 1, top + 2, z1, PARTY_STONE, 'party-south')
    for y in range(2, top + 2, 6):
        box(x0, y, z0, x0, y, z1, DRESS, 'party-course-west')
        box(x0, y, z1, x1 - 1, y, z1, DRESS, 'party-course-south')
    # Dress the exposed party-wall end grain at the two street corners. Without
    # this the grey brick wall reads as a vertical stripe on the primary stone
    # elevation because the east skin stops at z1 - 1 while the party wall runs
    # to z1.
    for qx, qz in ((x0, z0), (x0, z0 + 1), (x1 - 1, z1), (x1, z1)):
        box(qx, 1, qz, qx, top + 2, qz, DRESS, 'party-street-quoin')
    # Street skins respect the pan coupé instead of filling it back into a right angle.
    for x in range(x0, x1 + 1):
        for z in (z0, z0 + 1):
            if not cut_corner(x, z):
                box(x, 1, z, x, top, z, STONE, 'facade-north')
    for z in range(z0, z1):
        for x in (x1 - 1, x1):
            if not cut_corner(x, z):
                box(x, 1, z, x, top, z, STONE, 'facade-east')
    # Fill each roof column from the eave upward. The top block carries the
    # mansard stage material so the two-stage section is legible in elevation
    # and in plan: steep lower slope, break course, shallow upper slope, then
    # a single-axis ridge crest rather than a wide flat deck.
    ridge_axis = 'z' if plan.depth >= plan.width else 'x'
    ridge_dx = plan.width // 2
    ridge_dz = plan.depth // 2
    for dz in range(plan.depth):
        for dx in range(plan.width):
            if cut_corner(x0 + dx, z0 + dz):
                continue
            rise = max(1, _corner_rise(dx, dz, plan.width, plan.depth, roof_h, chamfer))
            # Build each column in the two mansard materials instead of one.
            # The steep lower slope is the dark tile, top+break_rise is an
            # explicit continuous break course, and the shallow upper cap is
            # the lighter deepslate. Painting only the topmost cell left the
            # two slopes the same colour, so the break never read from the
            # street and the crown looked like one shallow block.
            lower_top = min(rise, break_rise)
            box(x0 + dx, top + 1, z0 + dz, x0 + dx, top + lower_top, z0 + dz,
                ROOF, 'roof-lower')
            if rise > break_rise:
                box(x0 + dx, top + break_rise + 1, z0 + dz,
                    x0 + dx, top + rise, z0 + dz, ROOF_UPPER, 'roof-upper')
            if rise >= break_rise:
                put(x0 + dx, top + break_rise, z0 + dz, ROOF_BREAK, 'roof-break')
            if rise >= roof_h:
                # A single supported crest course.  The old extra block at
                # top+roof_h+1 read as detached from the roof in orbit views;
                # the ridge must stay continuous with the upper slope it crowns.
                put(x0 + dx, top + roof_h, z0 + dz, ROOF_RIDGE, 'roof-ridge')
    # With the floor-division profile full height occurs only on the ridge,
    # so every roof_h cell is a real crest cell rather than a wide plateau.
    # Record the whole band explicitly for the framework check.
    ridge_cells = [(x0 + dx, z0 + dz) for dz in range(plan.depth) for dx in range(plan.width)
                   if not cut_corner(x0 + dx, z0 + dz)
                   and _corner_rise(dx, dz, plan.width, plan.depth, roof_h, chamfer) >= roof_h]
    # The pan coupé face: the retaining wall sits on the true diagonal (sum == chamfer),
    # connecting the valid north-wall end to the valid east-wall start. The earlier
    # sum == chamfer - 1 line sat inside the cut and left a right-angle shoulder.
    diagonal = [] if chamfer <= 0 else [
        (x, z) for x in range(x0, x1 + 1) for z in range(z0, z1 + 1)
        if (x1 - x) + (z - z0) == chamfer]
    # Mark the pan-coupé roof eave and its first break in contrasting roof
    # materials, so the diagonal hip reads as a true intersecting slope in
    # plan and in orbit views instead of disappearing into the four faces.
    for (fx, fz) in diagonal:
        put(fx, top + 1, fz, ROOF_BREAK, 'chamfer-roof-eave')
    # Break material is already painted per roof column by the rise>=break_rise
    # test above.  An explicit constant-height break block on the diagonal
    # floated wherever the offset cell's own roof surface had not risen that far
    # (the isolated block seen at orbit_low_135), so it is not placed here.
    for (fx, fz) in diagonal:
        for y in range(1, top + 1):
            # The pan-coupe is a dressed third facade, not an infill of the
            # north/east flank material: a distinct cut-stone face makes the
            # 45-degree step read as a real chamfer in every orbit instead of
            # disappearing into the two street walls.
            put(fx, y, fz, STONE, 'chamfer-wall')
    # Heavy continuous plinth: both street bases and the pan coupé sit on the
    # same dressed stone course, so the commercial band reads as one mass at
    # framework tiers before any shopfront joinery is applied.
    for x in range(x0, x1 + 1):
        for z in (z0, z0 + 1):
            if not cut_corner(x, z):
                put(x, 1, z, BASE, 'street-plinth')
    for z in range(z0, z1):
        for x in (x1 - 1, x1):
            if not cut_corner(x, z):
                put(x, 1, z, BASE, 'street-plinth')
    for (fx, fz) in diagonal:
        put(fx, 1, fz, BASE, 'chamfer-plinth')
    # Projecting dressed plinth course at the outer street edge. This gives
    # the commercial base a continuous stone sill/plinth datum even where a
    # shop opening cuts the wall skin, and it wraps the pan-coupé continuously.
    for x in range(x0, x1 - chamfer + 1):
        put(x, 1, z0 - 1, DRESS, 'street-plinth-projection')
    for z in range(z0 + chamfer, z1):
        put(x1 + 1, 1, z, DRESS, 'street-plinth-projection')
    for (fx, fz) in diagonal:
        put(fx + 1, 1, fz - 1, DRESS, 'chamfer-plinth-projection')
    # The two hinge cells where the diagonal meets the north and east skins are
    # one common dressed column, so the pan coupé reads as one corner rather than
    # two unrelated wall ends with a grey stripe between them.
    for (fx, fz) in ((diagonal[0], diagonal[-1]) if diagonal else ()):
        for y in range(1, top + 1):
            put(fx, y, fz, DRESS, 'pan-coupe-corner-column')
    # Group the diagonal cells into wider lights rather than one-cell slots: the
    # pan-coupé glazing must read wider than a standard bay, and a 1-wide hole in
    # the cut face reads as a peephole.
    chamfer_lights = []
    chamfer_piers = []
    if len(diagonal) >= 9:
        # Two broad lights, each wider than the standard 2-cell bay, separated
        # by a central pilaster. This is the reference pan-coupé rhythm.
        mid = len(diagonal) // 2
        chamfer_piers = [diagonal[0], diagonal[mid], diagonal[-1]]
        chamfer_lights = [diagonal[1:mid], diagonal[mid + 1:-1]]
    elif len(diagonal) >= 5:
        # Keep end piers and centre one broad light explicitly wider than the
        # standard 2-cell bay. At the candidate chamfer 4..6 this reads as a
        # real pan-coupé opening rather than a peephole or a copied window.
        light_width = min(3, len(diagonal) - 2)
        start = (len(diagonal) - light_width) // 2
        chamfer_lights = [diagonal[start:start + light_width]]
        chamfer_piers = diagonal[:start] + diagonal[start + light_width:]
    elif diagonal:
        chamfer_lights = [diagonal]
        chamfer_piers = [diagonal[0], diagonal[-1]]
    for light in chamfer_lights:
        for li, floor in enumerate(floors[:-1]):
            bottom = floor + 1
            kind = 'shop' if li == 0 else 'window'
            h = opening_height(floor_roles[li], kind)
            if floor_roles[li] == 'attic':
                # Same one-course head band as the wing attic lights: the
                # pan-coupé light must not run into the cornice even though
                # it is wider than a standard bay.
                bottom = max(floor + 1, floors[li + 1] - h - 1)
            h = max(2, min(h, floors[li + 1] - bottom))
            # A pan-coupé light is wider than a wing bay, never taller: it
            # shares the wing sill and head lines exactly, so the two street
            # rhythms and the cut face all read on one horizontal grid.
            # The chamfer base is the corner shopfront: a solid stall riser,
            # glazing above it, and a sign band on the street side. This keeps
            # the pan-coupé from being another stacked residential window.
            kind = 'shop' if li == 0 else 'window'
            glazing = bottom + 1 if kind == 'shop' else bottom
            # The pan-coupé is a real wall on the diagonal, not a decal: open the
            # diagonal cell and set the glass one cell in, so the cut face gets a
            # genuine reveal and reads as a third elevation instead of a flat pane.
            if kind == 'shop' and tier >= 1:
                for (wx, wz) in light:
                    put(wx, bottom, wz, SHOP_TIMBER, 'chamfer-stall-riser')
            for (wx, wz) in light:
                for yy in range(glazing, bottom + h):
                    put(wx, yy, wz, AIR, 'chamfer-reveal')
                    put(wx - 1, yy, wz + 1,
                        SHOP_GLASS if kind == 'shop' else GLASS, 'chamfer-glazing')
            if tier >= 1:
                for (wx, wz) in light:
                    put(wx, bottom - 1, wz, slab('sandstone_slab'),
                        'chamfer-sill-backing')
                    put(wx + 1, bottom - 1, wz - 1, slab('sandstone_slab'),
                        'chamfer-sill')
                    put(wx, bottom + h, wz, slab('sandstone_slab'),
                        'chamfer-head-backing')
                    put(wx + 1, bottom + h, wz - 1, slab('sandstone_slab'),
                        'chamfer-head')
            if kind == 'shop' and tier >= 1:
                for (wx, wz) in light:
                    put(wx + 1, bottom + h, wz - 1, SIGN_BAND, 'chamfer-sign-band')
                    put(wx, bottom + h, wz, SHOP_TIMBER, 'chamfer-shop-lintel')
            openings.append({'face': 'chamfer', 'floor': li,
                             'u': light[0][0], 'z': light[0][1], 'y': bottom,
                             'width': len(light), 'height': h, 'kind': kind})
    for (px, pz) in chamfer_piers:
        for y in range(1, top + 1):
            put(px, y, pz, DRESS, 'chamfer-pilaster')
            put(px + 1, y, pz - 1, DRESS, 'chamfer-pilaster-relief')
    if tier >= 3:
        # Rustication wraps the solid pier run of the cut face, matching
        # the two street bases instead of stopping at the angle.
        for (px, pz) in chamfer_piers:
            for y in range(2, floors[1]):
                put(px, y, pz, BASE if y % 2 else STONE,
                    'chamfer-rustication')
    for (px, pz) in diagonal:
        for y, depth in ((top - 1, 1), (top, 2), (top + 1, 2)):
            put(px + depth, y, pz - depth,
                slab('sandstone_slab') if y == top + 1 else DRESS, 'chamfer-cornice')
        # Keep the chamfer corbel on the same course as the street-face corbel
        # row (top - 1). The old top - 2 row sat one course below the cornice
        # it supports, so the crown line visibly broke at the pan-coupe.
        put(px + 1, top - 1, pz - 1,
            stair('sandstone_stairs', 'north', 'top'), 'chamfer-corbel')
    # Chimney stacks: grouped slim flues seated on the actual roof surface,
    # never on a detached cap.  Three groups of three flues march from the
    # north slope across the ridge to the south/back slope, deliberately offset
    # from the dormer bays, so both the street crown and the back slope carry a
    # grouped skyline instead of one isolated stack.
    group_dz = (z0 + max(3, ridge_run - 4),
                z0 + max(4, ridge_run),
                z1 - max(3, ridge_run - 4))
    chimney_groups = []
    for dz in group_dz:
        group = []
        for cx in (x0 + plan.width // 2 - 2, x0 + plan.width // 2,
                   x0 + plan.width // 2 + 2):
            if not (x0 < cx < x1 and z0 < dz < z1) or cut_corner(cx, dz):
                continue
            base_y = max(top + 1, top + _corner_rise(cx - x0, dz - z0,
                                                     plan.width, plan.depth,
                                                     roof_h, chamfer))
            flue_top = min(top + roof_h + 1, base_y + 3)
            for yy in range(base_y, flue_top + 1):
                put(cx, yy, dz, ROOF, 'chimney-flue')
            if tier >= 2:
                put(cx, flue_top + 1, dz, ROOF_RIDGE, 'chimney-cap')
            group.append([cx, dz])
        if group:
            chimney_groups.append(group)
    noble_level = floor_roles.index('noble') if 'noble' in floor_roles else max(0, len(floor_roles) - 1)
    balcony_levels = [noble_level]
    jamb_state = state('sandstone_wall', east='tall', north='tall', south='tall', west='tall',
                       up='false', waterlogged='false')
    for face in faces:
        at, cub, bays = face['at'], face['cub'], face['bays']
        c0, c1 = face['span']
        entry_index = None
        if face['entry'] and bays:
            fraction = plan.entrance_fraction if plan.entrance_fraction is not None else .5
            entry_index = round(fraction * (len(bays) - 1))
        for li, floor in enumerate(floors[:-1]):
            ceiling = floors[li + 1]
            if li == 0:
                # The commercial base is a continuous band, not one opening per
                # bay: shops tile the whole street span with single-cell piers and
                # are interrupted only by the residential portal.  The upper
                # storeys continue to use the pitch-anchored two-cell bays.
                items = ground_layout[face['name']]
            else:
                items = [(bu, 2, 'window') for bu in bays]
            for bi, (bu, span, kind) in enumerate(items):
                bottom = floor + 1
                # Storey heights are articulated, not uniform: a shop bay is the tallest
                # and fills its bay so the base reads as one commercial band, the noble
                # floor keeps a tall window, the attic storey is the shortest.
                role = floor_roles[li]
                h = opening_height(role, kind)
                # The attic light is set in under the cornice: its head moves
                # close to the crown and leaves a deeper stone zone below it.
                # Adjust its base before clamping the height, otherwise the
                # attic window is compressed back to a square.
                if role == 'attic':
                    # Leave one solid course between the attic head and the
                    # cornice, so the light sits under the crown instead of
                    # running into the eave.
                    bottom = max(floor + 1, ceiling - h - 1)
                h = max(2, min(h, ceiling - bottom))
                box(*cub(bu, bu + span - 1, bottom, bottom + h - 1, 0, 1), AIR, 'opening')
                glazing = bottom
                if kind == 'shop' and tier >= 1:
                    # The stall riser is the solid dark-timber base a real shop window
                    # stands on; it belongs to the commercial base composition and must
                    # exist from the first facade tier, not only at tier 2.  It fills
                    # both wall depths, so the glazing above sits behind a real reveal.
                    box(*cub(bu, bu + span - 1, bottom, bottom, 0, 1), SHOP_TIMBER,
                        'stall-riser')
                    glazing = bottom + 1
                for du in range(span):
                    u = bu + du
                    if kind not in ('door', 'cafe_door'):
                        for yy in range(glazing, bottom + h):
                            put(*at(u, yy, 1), SHOP_GLASS if kind == 'shop' else GLASS,
                                'glazing')
                    elif tier >= 2:
                        for dy, half in enumerate(('lower', 'upper')):
                            put(*at(u, bottom + dy, 0), state('dark_oak_door', facing=face['door'],
                                half=half, hinge='left' if du == 0 else 'right', open='false',
                                powered='false'), 'functional-door')
                        for yy in range(bottom + 2, bottom + h):
                            put(*at(u, yy, 1), GLASS, 'door-transom')
                openings.append({'face': face['name'], 'floor': li, 'u': bu, 'y': bottom,
                    'width': span, 'height': h, 'kind': kind})
                if kind == 'shop':
                    # A shop bay keeps a dressed limestone surround at the street
                    # plane; the dark timber frame is set one cell outside it, so
                    # the commercial base reads as a framed opening inside stone,
                    # not as an unedged dark hole.
                    for uu in (bu - 1, bu + span):
                        for yy in range(bottom, bottom + h):
                            put(*at(uu, yy, 0), BASE, 'shop-pier')
                            if tier >= 1:
                                put(*at(uu, yy, -1), SHOP_TIMBER, 'shop-jamb')
                                put(*at(uu, yy, -2), DRESS, 'shop-stone-surround')
                    for uu in range(bu - 1, bu + span + 1):
                        put(*at(uu, bottom + h, 0), BASE, 'shop-lintel')
                        if tier >= 1:
                            put(*at(uu, bottom + h, -1), DRESS, 'shop-fascia')
                    if tier >= 1:
                        # Dark sign band sits within the dressed stone fascia;
                        # a projecting sill course ties all shop openings to
                        # the continuous stone plinth.
                        for uu in range(bu - 1, bu + span + 1):
                            put(*at(uu, bottom + h, -2), SIGN_BAND, 'sign-band')
                            put(*at(uu, bottom + h + 1, -1), DRESS, 'shop-cornice')
                            put(*at(uu, floor, -1), slab('sandstone_slab'),
                                'shop-sill')
                            put(*at(uu, floor, -2), slab('sandstone_slab'),
                                'shop-sill-projection')
                        # A dark transom and mullion divide the glazing so it reads
                        # as a framed shop window rather than a light roller shutter.
                        for uu in range(bu, bu + span):
                            put(*at(uu, bottom + h - 1, 0), SHOP_TIMBER,
                                'shop-transom')
                        if span >= 3:
                            for yy in range(bottom + 1, bottom + h):
                                put(*at(bu + span // 2, yy, 0), SHOP_TIMBER,
                                    'shop-mullion')
                elif tier >= 1:
                    surround = DRESS if kind == 'door' else jamb_state
                    for uu in (bu - 1, bu + 2):
                        for yy in range(bottom, bottom + h):
                            put(*at(uu, yy, 0), surround,
                                'door-jamb' if kind == 'door' else 'window-jamb')
                            put(*at(uu, yy, -1), DRESS,
                                'door-outer-jamb' if kind == 'door' else 'window-outer-jamb')
                    for uu in range(bu - 1, bu + 3):
                        put(*at(uu, bottom + h, 0), slab('sandstone_slab'), 'window-head')
                        put(*at(uu, bottom + h, -1), slab('sandstone_slab'),
                            'window-head-projection')
                        put(*at(uu, bottom + h, -2), slab('sandstone_slab'),
                            'window-head-cornice')
                        if kind == 'window':
                            sill_y = bottom - 1
                            put(*at(uu, sill_y, -1), slab('sandstone_slab'), 'window-sill')
                            put(*at(uu, sill_y, -2), slab('sandstone_slab'),
                                'window-sill-projection')
                            put(*at(uu, sill_y + 1, -1), DRESS, 'window-sill-support')
                    if kind == 'door':
                        # The residential entrance reads as a portal rather than an
                        # extra shop: dressed side piers on both street and outer
                        # planes, a raised stone threshold, and a projecting
                        # entablature with a cornice.
                        for yy in range(bottom, bottom + h):
                            put(*at(bu - 1, yy, 0), DRESS, 'entry-pier')
                            put(*at(bu + 2, yy, 0), DRESS, 'entry-pier')
                            put(*at(bu - 1, yy, -1), DRESS, 'entry-outer-pier')
                            put(*at(bu + 2, yy, -1), DRESS, 'entry-outer-pier')
                        for uu in range(bu - 2, bu + 4):
                            put(*at(uu, bottom - 1, -1), slab('sandstone_slab'),
                                'entry-threshold')
                            put(*at(uu, bottom + h, -1), DRESS,
                                'entry-entablature')
                            put(*at(uu, bottom + h + 1, -1),
                                slab('sandstone_slab'), 'entry-cornice')
                    if tier >= 1 and kind == 'window' and role != 'attic':
                        # Alternate triangular and flat pediments by bay and
                        # floor, so both lintel types appear on every elevation.
                        # The pediment is one projecting stone course on the
                        # window-head line (bottom+h), one course above the
                        # light and exactly one course below the storey course
                        # at the next floor line.  The old +1/+2 anchor landed
                        # on the next floor's sill and merged with the string
                        # course, which is why the review read no pediments.
                        # Flat = plain full-width band; triangular = same band
                        # with raking stair ends.  Both are built outward at
                        # d=-2, in front of the window-head projection.
                        for uu in range(bu - 1, bu + 3):
                            put(*at(uu, bottom + h, -2), DRESS, 'pediment-base')
                        pediments += 1
                        if (bi + li) % 2 == 0:
                            triangular_pediments += 1
                            put(*at(bu - 1, bottom + h, -2),
                                stair('sandstone_stairs',
                                      'east' if face['along'] == 'x' else 'south',
                                      'bottom'),
                                'pediment-rake-left')
                            put(*at(bu + 2, bottom + h, -2),
                                stair('sandstone_stairs',
                                      'west' if face['along'] == 'x' else 'north',
                                      'bottom'),
                                'pediment-rake-right')
                # The audited door-half states are not pasted onto the street
                # plane here: a block at d=0 fills the reveal and makes the
                # upper openings read as flush panels.  The cut opening and the
                # library stamp at the crown carry the audited vocabulary.
                if tier >= 3 and li > 0 and li not in balcony_levels:
                    box(*cub(bu - 1, bu + 2, bottom - 1, bottom - 1, -1, -1),
                        slab('sandstone_slab'), 'window-balcony')
                    for du in (0, 1):
                        put(*at(bu + du, bottom, -1), bars(face['along']), 'window-guard')
        # Balconies run the full street face and must meet at the pan coupé.
        # Extend the band four cells past the diagonal hinge at the cut corner
        # only, so its outer edge meets the diagonal balcony line rather than
        # stopping one cell short (the break visible in the low orbit views).
        b0, b1 = c0, c1
        if face['along'] == 'x':
            b1 = b1 + 4
        else:
            b0 = b0 - 4
        for li in balcony_levels:
            y = floors[li]
            # The long balcony is the recognition core of the elevation: a
            # projecting dressed-stone slab with a solid kerb and a tall iron
            # rail, continuous across the full face and returning at both ends.
            box(*cub(b0, b1, y, y, -4, -1), DRESS, 'balcony-plate')
            box(*cub(b0, b1, y - 1, y - 1, -3, -1), DRESS, 'balcony-corbel-band')
            if tier >= 1:
                for u in range(b0, b1 + 1):
                    put(*at(u, y + 1, -4), slab('sandstone_slab'), 'balcony-kerb')
                    put(*at(u, y + 2, -4), bars(face['along']), 'balcony-rail')
                    put(*at(u, y + 3, -4), slab('sandstone_slab'), 'balcony-handrail')
                for u in (b0, b1):
                    for d in (-3, -2, -1):
                        put(*at(u, y + 1, d), slab('sandstone_slab'), 'balcony-return-kerb')
                        put(*at(u, y + 2, d), bars('z' if face['along'] == 'x' else 'x'),
                            'balcony-return')
                        put(*at(u, y + 3, d), slab('sandstone_slab'), 'balcony-return')
            else:
                for u in range(b0, b1 + 1):
                    put(*at(u, y + 1, -4), DRESS, 'balcony-parapet')
                    put(*at(u, y + 2, -4), DRESS, 'balcony-parapet')
                    put(*at(u, y + 3, -4), slab('sandstone_slab'), 'balcony-cap')
                    if (u - b0) % 2 == 0:
                        put(*at(u, y + 3, -3), DRESS, 'balcony-baluster')
                for u in (b0, b1):
                    for d in (-3, -2, -1):
                        put(*at(u, y + 1, d), DRESS, 'balcony-return')
                        put(*at(u, y + 2, d), DRESS, 'balcony-return')
                        put(*at(u, y + 3, d), slab('sandstone_slab'), 'balcony-return')
            for bu in bays:
                put(*at(bu, y - 1, -1), stair('sandstone_stairs',
                    'south' if face['along'] == 'x' else 'west', 'top'), 'balcony-bracket')
        # Crown: a heavy projecting cornice with a continuous corbel row.
        # The corbels are placed on every cell so the cornice reads as a
        # built line rather than as isolated brackets, and the deepest course
        # is a slab so the roof eave starts inside a shadow line.
        for y, depth in ((top - 1, 1), (top, 2), (top + 1, 2)):
            box(*cub(c0, c1, y, y, -depth, -1),
                DRESS if y != top + 1 else slab('sandstone_slab'), 'cornice')
        for li in range(1, plan.storeys):
            if li not in balcony_levels:
                # A two-cell-deep string course reads as a real Haussmann band
                # in elevation and in perspective, not as a one-cell decal.
                box(*cub(c0, c1, floors[li], floors[li], -2, -1),
                    DRESS, 'storey-course')
                for u in range(c0, c1 + 1):
                    put(*at(u, floors[li], -2), slab('sandstone_slab'),
                        'storey-course-cap')
        # The corbel row must sit in the cornice soffit, not two courses
        # down across the window heads; putting it at top-1/top keeps the
        # bracket group on the crown and leaves the last window clear.
        for u in range(c0, c1 + 1):
            put(*at(u, top - 1, -2),
                stair('sandstone_stairs', face['door'], 'top'), 'cornice-corbel')
            put(*at(u, top, -2),
                slab('sandstone_slab'), 'cornice-corbel-cap')
        if plan.scheme == 'palace_front' and tier >= 1:
            # Competing composition. On a corner plot the angle itself is the visual
            # support, so it takes a vertical pier on both streets; the main street
            # entrance keeps a crowned centre. Without this the palace scheme renders
            # identically to the apartment scheme and the competition would be empty.
            pier = (c1 - 1, c1) if face['along'] == 'x' else (c0, c0 + 1)
            for u in pier:
                for y in range(2, top):
                    put(*at(u, y, -1), DRESS, 'angle-pier')
            if face['entry'] and entry_index is not None:
                entrance = bays[entry_index]
                for u in (entrance - 2, entrance + 3):
                    for y in range(2, top - 2):
                        put(*at(u, y, -1), DRESS, 'central-pilaster')
                for offset in range(3):
                    box(*cub(entrance - 2 + offset, entrance + 3 - offset,
                             floors[1] - 1 + offset, floors[1] - 1 + offset, -2, -2),
                        slab('sandstone_slab'), 'entry-pediment')
        if tier >= 3:
            # Rustication affects only solid piers, never painted across openings.
            for u in range(c0, c1 + 1):
                if any(bu - 1 <= u <= bu + 2 for bu in bays):
                    continue
                for y in range(2, floors[1]):
                    put(*at(u, y, 0), BASE if y % 2 else STONE, 'rustication')
    # String courses continue across the pan-coupé as real stone bands,
    # tying both street elevations and the cut corner into one horizontal
    # grid.  Without this carry-through the upper storeys can read as
    # disconnected vertical strips at the angle.
    for li in range(1, plan.storeys):
        if li not in balcony_levels:
            for (fx, fz) in diagonal:
                put(fx, floors[li], fz, slab('sandstone_slab'), 'chamfer-storey-course')
                put(fx + 1, floors[li], fz - 1, slab('sandstone_slab'),
                    'chamfer-storey-course-cap')
    # Continue the long balcony bands across the pan coupé as one continuous
    # dressed-stone shelf, with the same kerb, iron rail and handrail as the
    # street faces so the angle reads as part of the noble floor.
    for li in balcony_levels:
        y = floors[li]
        # Fill the true corner platform as a diagonal band between the inner
        # pan-coupé face and the outer rail line.  The old per-diagonal strip
        # met each street band only at one cell, which made the long balcony
        # read as broken in the low orbit views.
        for bx_ in range(x1 - chamfer - 1, x1 + 5):
            for bz_ in range(z0 - 4, z0 + chamfer + 2):
                s = (x1 - bx_) + (bz_ - z0)
                if chamfer - 8 <= s <= chamfer:
                    put(bx_, y, bz_, DRESS, 'chamfer-balcony-plate')
        # Rail, kerb and handrail follow the outer diagonal edge, joining the
        # north rail at (x1-chamfer+4, z0-4) to the east rail at
        # (x1+4, z0+chamfer-4).
        for (fx, fz) in diagonal:
            bx_, bz_ = fx + 4, fz - 4
            if x0 <= bx_ <= x1 + 4 and z0 - 4 <= bz_ <= z1:
                if tier >= 1:
                    put(bx_, y + 1, bz_, slab('sandstone_slab'), 'chamfer-balcony-kerb')
                    put(bx_, y + 2, bz_, diagonal_bars(), 'chamfer-balcony-rail')
                    put(bx_, y + 3, bz_, slab('sandstone_slab'),
                        'chamfer-balcony-handrail')
                else:
                    put(bx_, y + 1, bz_, DRESS, 'chamfer-balcony-parapet')
                    put(bx_, y + 2, bz_, DRESS, 'chamfer-balcony-parapet')
                    put(bx_, y + 3, bz_, slab('sandstone_slab'),
                        'chamfer-balcony-cap')
    # Glazed dormers: a two-cell light centred on each street bay, seated IN
    # the lower slope with stone cheeks, a sill, a lintel and a pitched cap.
    # Keeping the light two cells wide puts a dormer on every bay axis instead
    # of one off-centre light every few bays, which is what made the roof read
    # as bare and produced the 0/2/4 counts in review.
    for face in faces:
        at, bays, facing = face['at'], face['bays'], face['door']
        # Seat every dormer in the steep lower slope with its glazing on the
        # outer roof plane, one cell behind a stone cheek/sill/head frame.
        # The old d=1 glass sat behind the roof shell and read as a blank box.
        base = top + max(1, min(2, roof_h - 3))
        cap_y = min(top + roof_h, base + 4)
        for bu in bays:
            lights = (bu, bu + 1)
            for uu in lights:
                for yy in range(base, cap_y - 1):
                    put(*at(uu, yy, 0), AIR, 'dormer-cut')
                    put(*at(uu, yy, 1), DORMER_GLASS, 'dormer-glass')
            for uu in (bu - 1, bu + 2):
                for yy in range(base - 1, cap_y):
                    put(*at(uu, yy, 0), STONE, 'dormer-cheek')
                    put(*at(uu, yy, 1), STONE, 'dormer-cheek-backing')
            for uu in range(bu - 1, bu + 3):
                put(*at(uu, base - 1, 0), slab('sandstone_slab'), 'dormer-sill')
                put(*at(uu, cap_y - 1, 0), STONE, 'dormer-head')
                put(*at(uu, cap_y, 0),
                    stair('deepslate_tile_stairs', facing, 'bottom'),
                    'dormer-cap-slope')
                put(*at(uu, cap_y, 1), STONE, 'dormer-cap-back')
            if tier >= 2:
                for uu in range(bu - 1, bu + 3):
                    put(*at(uu, cap_y, -1), slab('sandstone_slab'),
                        'dormer-drip')
    # Stairs and the central circulation strip are explicit, with slab openings/headroom.
    stair_x, stair_z = cx, z0 + 10
    for lo, hi in zip(floors, floors[1:]):
        rise = hi - lo
        box(stair_x, hi, stair_z - 1, stair_x + 1, hi, stair_z + rise - 2, AIR, 'stairwell-opening')
        for step in range(rise):
            z, y = stair_z + step, lo + step + 1
            for x in (stair_x, stair_x + 1):
                if y > lo + 1: put(x, y - 1, z, WOOD, 'stair-stringer')
                put(x, y, z, stair('spruce_stairs', 'south'), 'stair-flight')
                stairs.append([x, y, z])
        if tier >= 3:
            for z in range(stair_z, stair_z + rise - 1):
                put(stair_x + 2, hi + 1, z, bars('z'), 'stairwell-guard')
    # Two apartments per floor around a shared entrance/stair corridor. Internal
    # doorways are deliberately open passages: no fake functional-door claims.
    rooms = []
    for li, y in enumerate(floors[:-1]):
        ceiling = floors[li + 1]
        if tier >= 2:
            for x in (cx - 3, cx + 4):
                box(x, y + 1, z0 + 2, x, ceiling - 1, z1 - 2, 'minecraft:calcite', 'interior-partition')
                for z in (z0 + 6, z1 - 6):
                    box(x, y + 1, z, x, y + 3, z + 1, AIR, 'interior-passage')
            if li == 0:
                entrance = faces[0]['bays'][entry_index] if entry_index is not None else cx
                box(min(entrance, cx - 3), y + 1, z0 + 2, max(entrance + 1, cx + 4), y + 3,
                    z0 + 5, AIR, 'foyer-cross-passage')
            for xa, xb in ((x0 + 2, cx - 4), (cx + 5, x1 - 2)):
                mid_z = z0 + plan.depth // 2
                box(xa, y + 1, mid_z, xb, ceiling - 1, mid_z, 'minecraft:calcite', 'room-partition')
                box(xa + 1, y + 1, mid_z, xa + 2, y + 3, mid_z, AIR, 'room-passage')
                rooms.append({'floor': li, 'bounds': [xa, y + 1, z0 + 2, xb, ceiling - 1, z1 - 2],
                    'use': 'cafe/residential service shell' if li == 0 else 'front living / rear bedroom shell'})
                if tier >= 3:
                    put(xa + 1, y + 1, z0 + 4, 'minecraft:bookshelf', 'interior-furniture')
                    put(xa + 2, y + 1, z0 + 4, stair('spruce_stairs', 'south'), 'interior-seat')
                    put(xa + 1, y + 1, z1 - 4, 'minecraft:crafting_table', 'interior-table')
            if tier >= 3:
                for z in (z0 + 7, z1 - 5):
                    put(cx - 1, y, z, 'minecraft:sea_lantern', 'corridor-light')
    if tier >= 3:
        # Rain leaders hang on both street skins, never on a party wall.
        for x in (x0 + 1, x1 - 1):
            for y in range(2, top + 1):
                put(x, y, z0 - 1, state('iron_chain', axis='y', waterlogged='false'), 'rain-leader')
        for z in (z0 + 1, z1 - 1):
            for y in range(2, top + 1):
                put(x1 + 1, y, z, state('iron_chain', axis='y', waterlogged='false'), 'rain-leader')
        # Street lamps flank the residential portal, below the first balcony.
        entrance = faces[0]['bays'][entry_index] if entry_index is not None else cx
        for x in (entrance - 1, entrance + 2):
            put(x, 5, z0 - 1, state('lantern', hanging='true', waterlogged='false'), 'entrance-lamp')
            put(x, 6, z0 - 1, slab('sandstone_slab'), 'lamp-bracket')
    # Apply source motifs after the interior, courses and crown. A whole source
    # cornice crop contains its own windows/backing and cannot be pasted here without
    # overwriting the accepted geometry. Place its applicable state motifs instead.
    from .technique_library import stamp as _technique_stamp, size_of as _technique_size
    source_state_audit = []
    if tier >= 3:
        source_state_audit, decorative = _corner_source_details(scene, faces, openings, refs)
    techniques = {} if tier == 0 else {'window_surround': len(openings), 'cornice': 1,
        'source_window_state': len(decorative), 'balcony_band': len(balcony_levels),
        'dormer': sum(len(f['bays']) for f in faces) * 2,
        'pediment': pediments, 'triangular_pediment': triangular_pediments,
        'shopfront': sum(1 for o in openings if o['kind'] == 'shop'),
        'roof_break': break_rise, 'roof_ridge_cells': len(ridge_cells),
        'library_stamp_count': len(stamp_audit),
        'source_state_cells': sum(row['survives'] for row in source_state_audit)}
    manifest = {'plan': plan.describe(), 'profile': 'reference_haussmann', 'techniques': techniques,
        'stamp_audit': stamp_audit,
        'source_state_audit': source_state_audit,
        'source_state_requirements': {
            'required_categories': ['thin_door_window', 'single_arm_wall', 'shaped_stair'],
            'required_faces': ['street_north', 'street_east'],
            'coverage': 'all_street_residential_openings',
            'game_behavior': 'NOT_RUN; paste must suppress block updates'},
        'structure': {'form': plan.form, 'width': plan.width, 'depth': plan.depth, 'storeys': plan.storeys,
            'floors_y': floors, 'top': top, 'roof_height': roof_h,
            'storey_courses': [{'y': floors[li], 'projection': 2,
                                'role': floor_roles[li - 1] + '_head'}
                               for li in range(1, plan.storeys)
                               if li not in balcony_levels],
            'balcony_corbel_band': {'y': floors[balcony_levels[0]] - 1,
                                    'projection': 3, 'continuous': True},
            'chimney_groups': chimney_groups,
            'attic': 'mansard attic volume under a steep lower slope and a shallow upper slope, with dormers seated in the lower slope',
            'crown': 'four-slope hip mansard, eaves on both street faces and a true pan-coupé diagonal eave',
            'corner_orientation': 'pan coupé at x_max,z_min (north-east street corner); the square south-west junction is the party-wall corner, so the right angle seen from orbit_low_225/orbit_high_225 is correct and is not the cut corner',
            'roof_section': {'profile': 'two-stage hip mansard: steep lower slope, explicit break, shallow upper slope to a continuous ridge',
                             'cross_section_perpendicular_to_ridge': [_corner_slope(d, roof_h, ridge_run)
                                                                      for d in range(ridge_run + 1)],
                             'north_to_centre': [_corner_rise((plan.width - 1) // 2, d, plan.width, plan.depth, roof_h, chamfer)
                                                for d in range(ridge_run + 1)],
                             'east_to_centre': [_corner_rise(plan.width - 1 - d,
                                                            (plan.depth - 1) // 2,
                                                            plan.width, plan.depth, roof_h, chamfer)
                                                for d in range(ridge_run + 1)],
                             'south_to_centre': [_corner_rise((plan.width - 1) // 2,
                                                             plan.depth - 1 - d,
                                                             plan.width, plan.depth, roof_h, chamfer)
                                                 for d in range(ridge_run + 1)],
                             'west_to_centre': [_corner_rise(d, (plan.depth - 1) // 2,
                                                            plan.width, plan.depth, roof_h, chamfer)
                                                for d in range(ridge_run + 1)],
                             'ridge_axis': 'z' if plan.depth >= plan.width else 'x',
                             'ridge_slope_run': ridge_run,
                             'ridge_run_definition': 'horizontal eave-to-ridge distance, not the length of the crest',
                             'ridge_cells': len(ridge_cells),
                             'ridge_span': ([min(c[0] for c in ridge_cells), max(c[0] for c in ridge_cells),
                                             min(c[1] for c in ridge_cells), max(c[1] for c in ridge_cells)]
                                            if ridge_cells else None),
                             'ridge_width_cells': ((max(c[0] for c in ridge_cells) - min(c[0] for c in ridge_cells) + 1)
                                                   if ridge_cells else 0),
                             'ridge_length_cells': ((max(c[1] for c in ridge_cells) - min(c[1] for c in ridge_cells) + 1)
                                                    if ridge_cells else 0),
                             'ridge_formula': 'full height requires every eave distance >= ridge_run; even-width plans compress the second central column by one cell so the crest is one cell wide',
                             'lower_run': break_run,
                             'lower_rise': break_rise,
                             'upper_run': max(1, ridge_run - break_run),
                             'upper_rise': max(0, roof_h - break_rise),
                             'lower_slope_per_cell': round((break_rise - 1) / max(1, break_run), 2),
                             'upper_slope_per_cell': round(max(0, roof_h - break_rise) /
                                                           max(1, ridge_run - break_run), 2),
                             'slope_break_distance': break_run,
                             'slope_break_rise': break_rise,
                             'chamfer_roof': {'eave_count': 5 if chamfer > 0 else 4,
                                              'diagonal_cells': len(diagonal),
                                              'diagonal_eave_rise': 1,
                                              'note': 'the pan-coupé diagonal is a real roof eave: rise is measured perpendicular to it, so the cut corner closes into the two street slopes instead of reading as a flat deck'},
                             'scope': 'generated geometry; style acceptance requires visual comparison'}},
        'walls': [{'name': name, 'role': role, 'openings': sum(o['face'] == name for o in openings)}
                  for name, role in [('street_north', 'primary'), ('street_east', 'primary'),
                                     ('party_west', 'party'), ('party_south', 'party')]],
        'bay_u': {f['name']: f['bays'] for f in faces},
        'bay_offsets': {f['name']: sorted([(x1 - chamfer) - (u + 1) for u in f['bays']]
                                          if f['along'] == 'x' else
                                          [u - (z0 + chamfer) for u in f['bays']])
                        for f in faces},
        'bay_anchor': {'pitch': pitch,
                       'anchor_north_end': [x1 - chamfer, z0],
                       'anchor_east_start': [x1, z0 + chamfer],
                       'shared_offsets': {f['name']: sorted(
                           [(x1 - chamfer) - (u + 1) for u in f['bays']]
                           if f['along'] == 'x' else
                           [u - (z0 + chamfer) for u in f['bays']])
                           for f in faces}},
        'balcony_floor_indices': balcony_levels,
        'long_balcony': {'levels': balcony_levels, 'projection': 4,
                         'chamfer_continuous': bool(diagonal), 'rail': 'iron or stone parapet'},
        'openings': openings, 'decorative_doors': decorative, 'stair_cells': stairs,
        'rooms': rooms, 'source_techniques': refs, 'technique_dispatch': dispatch_count,
        'cells': int(np.count_nonzero(scene.volume)),
        'scene_whd': [scene.volume.shape[2], scene.volume.shape[0], scene.volume.shape[1]],
        'limitations': ['Interior room shells and basic furniture only; no complete kitchens/bathrooms.',
            'Both party walls are blind; the two neighbouring plots are contextual and not exported.',
            'Source decorative door halves need suppressed updates; game behavior NOT_RUN.'],
        'unsupported_decisions': [
            {'id': 'internal_courtyard', 'status': 'deferred',
             'reason': 'Deep-plot courtyard inference is not implemented before framework review.'},
            {'id': 'basement_and_underground_level', 'status': 'deferred',
             'reason': 'No confirmed underground programme; shop openings are not basement evidence.'},
            {'id': 'adjacent_building_roof_step', 'status': 'context',
             'reason': 'Neighbouring plots and cornice/roof mismatch belong to the city context layer.'},
            {'id': 'technique_library_source_state_translation', 'status': 'active' if tier >= 3 else 'next_tier',
             'reason': 'Audited source window joinery, one-sided wall limbs and inner stair '
                       'soffits are rotated into every street residential opening. '
                       'source_state_audit binds original source coordinates to surviving exported cells.'}],
        'game_acceptance': 'PENDING'}
    return scene, manifest
