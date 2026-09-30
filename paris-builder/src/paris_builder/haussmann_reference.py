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
BASE = 'minecraft:polished_andesite'
WOOD = 'minecraft:spruce_planks'
ROOF = 'minecraft:deepslate_tiles'
GLASS = 'minecraft:light_gray_stained_glass'
#: Shop bays get their own vocabulary: a dark timber sign band over the glazing and a
#: solid stall riser under it. Sharing the residential surround is what made the ground
#: floor read as a row of oversized windows instead of a commercial base.
SIGN_BAND = 'minecraft:dark_oak_planks'


def stair(name, facing, half='bottom', shape='straight'):
    return state(name, facing=facing, half=half, shape=shape, waterlogged='false')


def slab(name, kind='top'):
    return state(name, type=kind, waterlogged='false')


def bars(along='x'):
    return state('iron_bars', east=str(along == 'x').lower(), west=str(along == 'x').lower(),
                 north=str(along == 'z').lower(), south=str(along == 'z').lower(), waterlogged='false')


def evidence():
    ids = ('s3-window-bay', 's3-upper-balcony', 's3-cornice', 's3-dormer',
           's3-chimney', 's3-roof-section', 'b2-base', 'b2-pilaster')
    rows = []
    for ident in ids:
        folder = ROOT / 'knowledge/library-v3/reference-techniques' / ident
        raw = json.loads((folder / 'record.json').read_text(encoding='utf-8'))
        if hashlib.sha256((folder / 'detail.schem').read_bytes()).hexdigest() != raw['schematic_sha256']:
            raise ValueError('Source sample changed: ' + ident)
        rows.append({'id': 'v3:' + ident, 'source': raw['source'], 'source_sha256': raw['source_sha256'],
                     'bbox': raw['source_bbox_xyz_half_open'], 'record_sha256': hashlib.sha256(
                         (folder / 'record.json').read_bytes()).hexdigest(),
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
def _corner_slope(d, roof_h, run):
    """Steep lower mansard and shallow upper slope across the available half-span."""
    run = max(2, run)
    knee = min(3, run - 1)
    eave = 1
    break_rise = max(eave + 1, roof_h - max(1, roof_h // 3))
    if d <= knee:
        return eave + round((break_rise - eave) * max(0, d) / knee)
    return min(roof_h, break_rise + round((roof_h - break_rise) * (d - knee) / (run - knee)))


def _corner_rise(dx, dz, wid, dep, roof_h):
    """Hip the roof from all four eaves; the blind party parapets remain separate."""
    run = max(2, min(wid, dep) // 2 - 1)
    return _corner_slope(min(dx, wid - 1 - dx, dz, dep - 1 - dz), roof_h, run)


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
    x0, z0 = 6, 6
    x1, z1 = x0 + plan.width - 1, z0 + plan.depth - 1
    heights = [7, 7] + [6] * (plan.storeys - 2)
    floors = [1]
    for h in heights:
        floors.append(floors[-1] + h)
    top = floors[-1]
    roof_h = plan.roof_height or 7
    scene = Scene(x1 + 10, top + roof_h + 7, z1 + 10)
    put, box = scene.put, scene.box
    pitch = plan.bay_pitch or 5
    cx = x0 + plan.width // 2

    #: The pan coupé. The corner is cut on the diagonal so the two streets meet on a
    #: third, narrower face — the defining feature of the reference corner building, and
    #: its absence is what the review kept rejecting as "a right-angle corner".
    chamfer = plan.chamfer if plan.chamfer else max(3, min(5, min(plan.width, plan.depth) // 6))

    def cut_corner(x, z):
        """True inside the triangle the pan coupé removes at the shared corner."""
        return (x1 - x) + (z - z0) < chamfer

    def bay_axis(start, end, from_end):
        """Bays counted from the SHARED corner, so both streets use one pitch.

        Each street used to centre its own bays independently, so two elevations of
        different length came out with rhythms anchored nowhere near the angle; the
        review rejected that as "north 3 bays against east 5, no common corner column".
        The corner is the one point both streets share, so both count from it.
        """
        bays = []
        if from_end:
            u = end - 2
            while u - 1 >= start:
                bays.append(u)
                u -= pitch
        else:
            u = start + 2
            while u + 2 <= end:
                bays.append(u)
                u += pitch
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
                'bays': bay_axis(*span, horizontal), 'length': length, 'entry': entry}

    faces = [make_face('street_north', x0, plan.width, True, True, 'x'),
             make_face('street_east', z0, plan.depth, False, False, 'z')]
    openings, decorative, stairs = [], [], []
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
    box(x0, 1, z0, x0, top + roof_h + 1, z1, 'minecraft:stone_bricks', 'party-west')
    box(x0, 1, z1, x1 - 1, top + roof_h + 1, z1, 'minecraft:stone_bricks', 'party-south')
    box(x0, 1, z0, x1 - chamfer, top, z0 + 1, STONE, 'facade-north')
    box(x1 - 1, 1, z0 + chamfer, x1, top, z1 - 1, STONE, 'facade-east')
    # A shell, not solid plates: the mansard profile, minus the cut corner.
    for dz in range(plan.depth):
        for dx in range(plan.width):
            if cut_corner(x0 + dx, z0 + dz):
                continue
            put(x0 + dx, top + _corner_rise(dx, dz, plan.width, plan.depth, roof_h),
                z0 + dz, ROOF, 'roof-shell')
    # The pan coupé face: a stair of cells along the diagonal, with a pilaster at each
    # end, a glazed bay per storey, and a cornice that follows the same diagonal so the
    # eaves stay continuous round the angle instead of breaking into a right-angle step.
    diagonal = [(x, z) for x in range(x0, x1 + 1) for z in range(z0, z1 + 1)
                if (x1 - x) + (z - z0) == chamfer - 1]
    for (fx, fz) in diagonal:
        for y in range(1, top + 1):
            put(fx, y, fz, STONE, 'chamfer-wall')
    windows = diagonal[1:-1] if len(diagonal) >= 4 else [diagonal[len(diagonal) // 2]]
    for (wx, wz) in windows:
        for li, floor in enumerate(floors[:-1]):
            bottom = floor + 1
            h = 5 if li <= 1 else (3 if li == len(floors) - 2 else 4)
            h = max(2, min(h, floors[li + 1] - bottom))
            for yy in range(bottom, bottom + h):
                put(wx, yy, wz, GLASS, 'chamfer-glazing')
                put(wx - 1, yy, wz + 1, AIR, 'chamfer-opening')
                put(wx - 2, yy, wz + 2, AIR, 'chamfer-reveal')
            openings.append({'face': 'chamfer', 'floor': li, 'u': wx, 'y': bottom,
                             'width': 1, 'height': h, 'kind': 'window'})
    if tier >= 1:
        for (px, pz) in (diagonal[0], diagonal[-1]):
            for y in range(2, top):
                put(px, y, pz, DRESS, 'chamfer-pilaster')
        for (px, pz) in diagonal:
            put(px, top + 1, pz, slab('sandstone_slab'), 'chamfer-cornice')
            put(px - 1, top + 1, pz + 1, slab('sandstone_slab'), 'chamfer-cornice')
    # Chimney stacks sit on the two party lines, with supported clay flues.
    for dz in (z0 + 8, z1 - 8):
        y = top + _corner_rise(1, dz - z0, plan.width, plan.depth, roof_h)
        box(x0 + 1, y, dz, x0 + 1, top + roof_h + 2, dz + 1, 'minecraft:bricks', 'chimney')
        if tier >= 2:
            for zz in (dz, dz + 1):
                put(x0 + 1, top + roof_h + 3, zz, state('anvil', facing='north'), 'chimney-cap')
                if tier >= 3:
                    put(x0 + 1, top + roof_h + 4, zz, 'minecraft:flower_pot', 'chimney-pot')
    for dx in (x0 + 8, x1 - 8):
        y = top + _corner_rise(dx - x0, 1, plan.width, plan.depth, roof_h)
        box(dx, y, z1 - 1, dx + 1, top + roof_h + 2, z1 - 1, 'minecraft:bricks', 'chimney')
        if tier >= 2:
            for xx in (dx, dx + 1):
                put(xx, top + roof_h + 3, z1 - 1, state('anvil', facing='north'), 'chimney-cap')
                if tier >= 3:
                    put(xx, top + roof_h + 4, z1 - 1, 'minecraft:flower_pot', 'chimney-pot')
    balcony_levels = [1, max(2, plan.storeys - 2)]
    if plan.scheme == 'plain_terrace':
        balcony_levels = [1]
    jamb_state = state('sandstone_wall', east='tall', north='tall', south='tall', west='tall',
                       up='false', waterlogged='false')
    for face in faces:
        at, cub, bays = face['at'], face['cub'], face['bays']
        c0, c1 = face['span']
        entry_index = None
        if face['entry']:
            fraction = plan.entrance_fraction if plan.entrance_fraction is not None else .5
            entry_index = round(fraction * (len(bays) - 1))
        for li, floor in enumerate(floors[:-1]):
            ceiling = floors[li + 1]
            for bi, bu in enumerate(bays):
                bottom = floor + 1
                kind = 'window'
                if li == 0:
                    kind = 'door' if (face['entry'] and bi == entry_index) else 'shop'
                    # A separate cafe entrance keeps the residence door independent.
                    if face['entry'] and bi == (0 if entry_index != 0 else len(bays) - 1):
                        kind = 'cafe_door'
                # Storey heights are articulated, not uniform: a shop bay is the tallest
                # and fills its bay so the base reads as one commercial band, the noble
                # floor keeps a tall window, the attic storey is the shortest.
                if kind == 'shop':
                    span = max(2, pitch - 1)
                    h = 6
                else:
                    span = 2
                    h = 5 if li <= 1 else (3 if li == len(floors) - 2 else 4)
                h = max(2, min(h, ceiling - bottom))
                box(*cub(bu, bu + span - 1, bottom, bottom + h - 1, 0, 1), AIR, 'opening')
                glazing = bottom
                if kind == 'shop' and tier >= 2:
                    # The stall riser is the solid base a real shop window stands on.
                    box(*cub(bu, bu + span - 1, bottom, bottom, 0, 1), BASE, 'stall-riser')
                    glazing = bottom + 1
                for du in range(span):
                    u = bu + du
                    if kind not in ('door', 'cafe_door'):
                        for yy in range(glazing, bottom + h):
                            put(*at(u, yy, 1), GLASS, 'glazing')
                    elif tier >= 2:
                        for dy, half in enumerate(('lower', 'upper')):
                            put(*at(u, bottom + dy, 0), state('dark_oak_door', facing=face['door'],
                                half=half, hinge='left' if du == 0 else 'right', open='false',
                                powered='false'), 'functional-door')
                        for yy in range(bottom + 2, bottom + h):
                            put(*at(u, yy, 1), GLASS, 'door-transom')
                openings.append({'face': face['name'], 'floor': li, 'u': bu, 'y': bottom,
                    'width': span, 'height': h, 'kind': kind})
                if tier >= 1 and kind == 'shop':
                    # A shop bay takes a plain pier and a lintel of its own; it never gets
                    # the residential sill-and-surround treatment.
                    for uu in (bu - 1, bu + span):
                        for yy in range(bottom, bottom + h):
                            put(*at(uu, yy, 0), BASE, 'shop-pier')
                    for uu in range(bu - 1, bu + span + 1):
                        put(*at(uu, bottom + h, 0), BASE, 'shop-lintel')
                    if tier >= 2:
                        for uu in range(bu - 1, bu + span + 1):
                            put(*at(uu, bottom + h, 0), SIGN_BAND, 'sign-band')
                        if span >= 3:
                            for yy in range(bottom + 1, bottom + h):
                                put(*at(bu + span // 2, yy, 0), BASE, 'shop-mullion')
                elif tier >= 1:
                    for uu in (bu - 1, bu + 2):
                        for yy in range(bottom, bottom + h):
                            put(*at(uu, yy, 0), jamb_state, 'window-jamb')
                    for uu in range(bu - 1, bu + 3):
                        put(*at(uu, bottom + h, 0), slab('sandstone_slab'), 'window-head')
                        if kind == 'window':
                            put(*at(uu, floor, -1), slab('sandstone_slab'), 'window-sill')
                if tier >= 2 and li > 0:
                    for dx, source_state in enumerate(door_states):
                        value = transform_state(source_state, turns=2)
                        for yy in range(bottom, bottom + h):
                            put(*at(bu + dx, yy, 0), value, 'source-thin-window')
                            decorative.append({'xyz': list(at(bu + dx, yy, 0)), 'state': value,
                                'source_id': 'v3:s3-window-bay',
                                'transformation': 'rotate_y_180; retain half=lower'})
                if tier >= 3 and li > 0 and li not in balcony_levels:
                    for du in (0, 1):
                        put(*at(bu + du, bottom, -1), bars(face['along']), 'window-guard')
        # Balconies run the full street face; the two faces meet at the angle.
        b0, b1 = c0, c1
        for li in balcony_levels:
            y = floors[li]
            box(*cub(b0, b1, y, y, -3, -1), slab('sandstone_slab') if tier else STONE, 'balcony-plate')
            if tier >= 2:
                for u in range(b0, b1 + 1):
                    put(*at(u, y + 1, -3), bars(face['along']), 'balcony-rail')
                for u in (b0, b1):
                    for d in (-2, -1):
                        put(*at(u, y + 1, d), bars('z' if face['along'] == 'x' else 'x'), 'balcony-return')
                for bu in bays:
                    put(*at(bu, y - 1, -1), stair('sandstone_stairs',
                        'south' if face['along'] == 'x' else 'west', 'top'), 'balcony-bracket')
        if tier >= 1:
            for y, depth in ((top - 1, 1), (top, 2), (top + 1, 1)):
                box(*cub(c0, c1, y, y, -depth, -1),
                    slab('sandstone_slab') if y == top + 1 else DRESS, 'cornice')
            for li in range(1, plan.storeys):
                if li not in balcony_levels:
                    box(*cub(c0, c1, floors[li], floors[li], 0, 0),
                        slab('sandstone_slab'), 'storey-course')
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
                    put(*at(u, y, 0), BASE if y % 2 else 'minecraft:andesite', 'rustication')
    # Glazed dormers: seated IN the street slope, each with a sill, a lintel, stone
    # cheeks that follow the slope, and a real pitched cap. The earlier version was a
    # plain box (two glass cells and one flat cap), which is what the review kept
    # rejecting as an unreadable dormer rather than a window in the roof.
    for face in faces:
        at, bays, facing = face['at'], face['bays'], face['door']
        run = max(2, min(plan.width, plan.depth) // 2 - 1)
        base = top + _corner_slope(1, roof_h, run)
        for bu in bays:
            # Cut the slope open where the dormer sits, or the rising roof passes through.
            for uu in range(bu - 1, bu + 3):
                for d in (1, 2):
                    put(*at(uu, top + _corner_slope(d, roof_h, run), d), AIR, 'dormer-cut')
            # Cheeks: stone jambs on both sides, following the slope downwards.
            for d in (1, 2):
                for uu in (bu - 1, bu + 2):
                    for dy in range(-1, 3):
                        put(*at(uu, base + dy, d), STONE, 'dormer-cheek')
            # Sill, glazing and lintel on the street-facing plane of the dormer.
            for uu in (bu, bu + 1):
                put(*at(uu, base - 1, 1), slab('sandstone_slab'), 'dormer-sill')
                for dy in range(0, 2):
                    put(*at(uu, base + dy, 1), GLASS, 'dormer-glass')
                put(*at(uu, base + 2, 1), STONE, 'dormer-head')
            # A pitched cap: a stair course facing the street over a slab course behind.
            for uu in range(bu - 1, bu + 3):
                put(*at(uu, base + 3, 1),
                    stair('minecraft:deepslate_tile_stairs', facing, 'bottom'), 'dormer-cap-slope')
                put(*at(uu, base + 3, 2), STONE, 'dormer-cap-back')
                put(*at(uu, base + 4, 2),
                    slab('minecraft:deepslate_tile_slab', 'top'), 'dormer-cap-ridge')
            if tier >= 2:
                for uu in range(bu - 1, bu + 3):
                    put(*at(uu, base + 3, 0), slab('sandstone_slab'), 'dormer-drip')
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
    techniques = {} if tier == 0 else {'window_surround': len(openings), 'cornice': 1,
        'source_window_state': len(decorative), 'balcony_band': len(balcony_levels),
        'dormer': sum(len(f['bays']) for f in faces) * 2}
    manifest = {'plan': plan.describe(), 'profile': 'reference_haussmann', 'techniques': techniques,
        'structure': {'form': plan.form, 'width': plan.width, 'depth': plan.depth, 'storeys': plan.storeys,
            'floors_y': floors, 'top': top, 'roof_height': roof_h, 'attic': 'additional roof space',
            'crown': 'four-slope, eaves on both street faces',
            'roof_section': {'north_to_centre': [_corner_rise(plan.width // 2, d, plan.width, plan.depth, roof_h)
                                                for d in range(plan.depth // 2 + 1)],
                             'east_to_centre': [_corner_rise(d, plan.depth // 2, plan.width, plan.depth, roof_h)
                                               for d in range(plan.width // 2 + 1)],
                             'scope': 'generated geometry; style acceptance requires visual comparison'}},
        'walls': [{'name': name, 'role': role, 'openings': sum(o['face'] == name for o in openings)}
                  for name, role in [('street_north', 'primary'), ('street_east', 'primary'),
                                     ('party_west', 'party'), ('party_south', 'party')]],
        'bay_u': {f['name']: f['bays'] for f in faces}, 'balcony_floor_indices': balcony_levels,
        'openings': openings, 'decorative_doors': decorative, 'stair_cells': stairs,
        'rooms': rooms, 'source_techniques': refs, 'cells': int(np.count_nonzero(scene.volume)),
        'scene_whd': [scene.volume.shape[2], scene.volume.shape[0], scene.volume.shape[1]],
        'limitations': ['Interior room shells and basic furniture only; no complete kitchens/bathrooms.',
            'Both party walls are blind; the two neighbouring plots are contextual and not exported.',
            'Source decorative door halves need suppressed updates; game behavior NOT_RUN.'],
        'game_acceptance': 'PENDING'}
    return scene, manifest
