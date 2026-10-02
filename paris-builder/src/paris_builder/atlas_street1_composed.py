"""Execute a validated pavilion composition with source-backed atlas pieces.

All design coordinates are relative to the old wing origin; a one-cell origin
margin lets the corner move outward without negative coordinates. Structural
closure is written first. Source pieces then retain their frozen states and are
audited against replayed original sources after export.
"""
from pathlib import Path

import numpy as np

from . import atlas_street1 as kit
from . import technique_library as library
from .architecture import Scene, split_state
from .atlas_assembly import (
    Assembler, bay_positions, load_piece, piece_source, rotate_volume,
    subcut_volume, validate_vanilla)
from .atlas_composition import validate_composition
from .exporter import dump_json, write_schematic
from .schematic import load_schematic


ROOT = library.ROOT
NAME = 'ATLAS composed corner apartment (grouped pavilions)'


def _read(asm, ident):
    return (load_schematic(ROOT / asm.derived[ident]['path'])
            if ident in asm.derived else load_piece(ident))


def _cut(asm, ident, parent, bbox, note):
    read = _read(asm, parent)
    x0, y0, z0, x1, y1, z1 = bbox
    volume, palette = subcut_volume(read.volume, read.id_to_state,
                                    x0, x1, y0, y1, z0, z1)
    asm.register_derived(ident, volume, palette, note, source_id=parent,
                         operations=[{'op': 'subcut', 'bbox': bbox}])
    return ident


def _rotate(asm, ident, parent, turns):
    read = _read(asm, parent)
    volume, palette = rotate_volume(read.volume, read.id_to_state, turns)
    asm.register_derived(ident, volume, palette,
                         'Source-backed spatial and frozen-state rotation turns=%d' % turns,
                         source_id=parent, operations=[{'op': 'rotate', 'turns': turns}])
    return ident


def _positions(wing, start, phase, rhythm):
    result = bay_positions(start, wing['bay_count'], rhythm, phase)
    for boundary in wing['pier_boundaries']:
        for index in range(boundary['after_bay'] + 1, len(result)):
            result[index] += boundary['extra_pitch']
    return result


def _segments(wing, positions, span, roof_start):
    result = []
    for group in wing['groups']:
        first, last = group['bays'][0], group['bays'][-1]
        lo = positions[first]
        hi = positions[last + 1] if last + 1 < len(positions) else span
        result.append({'group': group['id'], 'role': group['role'],
                       'lo': lo, 'hi': hi,
                       'roof_lo': roof_start if first == 0 else lo,
                       'projection': wing['bays'][first]['projection']})
    return result


def _projection_at(segments, position):
    for segment in segments:
        if segment['lo'] <= position < segment['hi']:
            return segment['projection']
    return 0


def _fill(asm, xs, zs, spans, segments, origin, tops, dry_run=False):
    """Backing, widened piers, stepped band returns and true-slope end walls.

    No filler is written after a source piece. A one-column dark end shell
    follows the source profile and owns the source-backed strips' reserved tail
    line. It closes half-model gaps without changing frozen wall/slab states.

    In a dry run the cell counting still happens - the manifest needs it - but the
    voxels are not written, so walking the whole driver costs no scene traffic.
    """
    counts = {'core_cells': 0, 'pier_cells': 0, 'firewall_cells': 0, 'band_return_cells': 0}
    xw, zw = spans

    def put(x, y, z, owner, party=False, material=None):
        value = material or (kit.FILL_JOINT if party and kit.party_joint(x, y, z) else kit.FILL)
        if not dry_run:
            asm.scene.put(x + origin, y, z + origin, value, 'fill:' + owner)
        counts[owner + '_cells'] += 1

    for x in range(11, xw):
        projection = _projection_at(segments['north'], x)
        start = 6 - projection if x >= xw - 2 else 8 - projection
        for z in range(start, kit.WING_DEPTH):
            for y in range(kit.WALL_TOP_Y + 1):
                put(x, y, z, 'core', z == kit.WING_DEPTH - 1 or x == xw - 1)
    for z in range(11, zw):
        projection = _projection_at(segments['west'], z)
        start = 6 - projection if z >= zw - 2 else 8 - projection
        for x in range(start, kit.WING_DEPTH):
            for y in range(kit.WALL_TOP_Y + 1):
                put(x, y, z, 'core', x == kit.WING_DEPTH - 1 or z == zw - 1)

    for side, positions in (('north', xs), ('west', zs)):
        for index, before in enumerate(positions[:-1]):
            after = positions[index + 1]
            p0 = _projection_at(segments[side], before)
            p1 = _projection_at(segments[side], after)
            for axis in range(before + 4, after):
                for inward in range(6 - max(p0, p1), 8):
                    for y in range(kit.WALL_TOP_Y + 1):
                        x, z = (axis, inward) if side == 'north' else (inward, axis)
                        put(x, y, z, 'pier')
                # Only hidden, one-course horizontal bearings. Visible band
                # ends and pier faces belong to source components, never to
                # a tall smooth slab in front of windows/cornice detail.
                for y in (10, 25, 29):
                    for inward in range(6, 8):
                        x, z = (axis, inward) if side == 'north' else (inward, axis)
                        put(x, y, z, 'band_return')

    def firewall(x, z, top, dark=False):
        for y in range(kit.WALL_TOP_Y + 1, top + 1):
            put(x, y, z, 'firewall', True, 'minecraft:deepslate_tiles' if dark else None)

    for x in range(kit.WING_DEPTH, xw):
        firewall(x, kit.WING_DEPTH - 1, kit.FIREWALL_TOP_Y)
    for z in range(kit.WING_DEPTH, zw):
        firewall(kit.WING_DEPTH - 1, z, kit.FIREWALL_TOP_Y)
    for side, span in (('north', xw), ('west', zw)):
        projection = segments[side][-1]['projection']
        roof_front = kit.COMMON_Z - projection
        for inward in range(0, kit.WING_DEPTH):
            local = inward - roof_front
            top = (kit.Y_ROOF + tops[local]
                   if 0 <= local < len(tops) else kit.WALL_TOP_Y)
            x, z = (span - 1, inward) if side == 'north' else (inward, span - 1)
            firewall(x, z, top, True)
    return counts


def _roof_backing(asm, derived, segments, origin):
    """Close roof-shell wall-model gaps with an interior dark structural layer.

    The rotated roof strips contain thin frozen walls running along the wing.
    Their connection states are architectural detail and remain unchanged. A
    full block one cell inward closes the view through the model's side gaps;
    it is written before any source stamp and never on the visible wall cell.
    """
    count = 0
    for side in ('north', 'west'):
        read = _read(asm, derived['roof' + ('_w' if side == 'west' else '')])
        height, depth, width = read.volume.shape
        stride = width if side == 'north' else depth
        for segment in segments[side]:
            projection = segment['projection']
            for start in range(segment['roof_lo'], segment['hi'], stride):
                length = min(stride, segment['hi'] - start)
                for dy in range(height):
                    for dz in range(depth):
                        for dx in range(width):
                            if (dx if side == 'north' else dz) >= length:
                                continue
                            name, props = split_state(read.id_to_state[int(read.volume[dy, dz, dx])])
                            if not name.endswith('_wall') or props.get('up') != 'false':
                                continue
                            x = start + dx if side == 'north' else 3 - projection + dx + 1
                            z = 3 - projection + dz + 1 if side == 'north' else start + dz
                            asm.scene.put(x + origin, kit.Y_ROOF + dy, z + origin,
                                          'minecraft:deepslate_tiles', 'fill:roof_backing')
                            count += 1
    return count


def _junction_policy(asm, width, depth, origin):
    """Named ownership transitions, intersected with both source-piece boxes.

    Permissions are declared by assembly layers, never by mismatch samples.
    An unexpected role pair, complete loss, clipped piece or late fill cannot
    pass by broadening this contract to the whole scene.
    """
    zones = []

    def permit(before, after, y0, y1, reason, bounds=None):
        zones.append((before, after,
                      bounds or [0, y0, 0, width, y1, depth], reason))

    permit('roof-north', 'roof-west', 29, 46,
           'Orthogonal roof slopes meet inside the L-shaped corner',
           [3 + origin, 29, 11 + origin, 23 + origin, 46, 23 + origin])
    for side in ('north', 'west'):
        roof = 'roof-' + side
        permit(roof, 'balcony-upper-' + side, 29, 31,
               'Upper balcony backing meets the bottom two roof courses')
        permit('balcony-upper-' + side, 'cornice-' + side, 27, 31,
               'Cornice owns the upper rail and terrace transition')
        permit(roof, 'cornice-' + side, 29, 36,
               'Cornice and gutter own the roof foot joint')
        permit('balcony-lower-' + side, 'bay-noble-' + side, 12, 16,
               'Noble source window owns the balcony backing at the floor junction')
        permit('balcony-lower-' + side, 'bay-standard-' + side, 10, 12,
               'Standard window head meets lower balcony supports')
        permit('base-arcade-' + side, 'bay-standard-' + side, 6, 9,
               'Standard window owns the arcade/window transition, preserving glass')
        permit('base-arcade-' + side, 'pier-standard-' + side, 6, 9,
               'Source standard half-pier owns the arcade head at a widened grouping column')
        permit('balcony-lower-' + side, 'pier-standard-' + side, 10, 12,
               'Source standard half-pier head meets the lower balcony backing')
        permit('balcony-lower-' + side, 'pier-noble-' + side, 12, 16,
               'Source noble half-pier articulates the grouping column and closes the lower band end')
        permit('bay-noble-' + side, 'plant-noble-' + side, 19, 23,
               'Source hanging planter attaches at the upper noble window sill without replacing its glass')
        for grade in ('lower', 'upper', 'pavilion'):
            dormer = 'dormer-' + grade + '-' + side
            y0, y1 = (31, 38) if grade == 'lower' else (36, 43)
            permit(roof, dormer, y0, y1, 'Source dormer embeds into its designed roof stratum')
            if grade == 'lower':
                permit('cornice-' + side, dormer, 31, 36,
                       'Lower dormer cheeks meet the cornice/gutter junction')
            else:
                permit('dormer-lower-' + side, dormer, 36, 38,
                       'Upper dormer owns the two shared courses at the slope break')
        permit(roof, 'chimney-' + side, 40, 46,
               'Narrow complete chimney cluster embeds its feet into the ridge surface')
        for grade in ('upper', 'pavilion'):
            permit('dormer-' + grade + '-' + side, 'chimney-' + side, 40, 43,
                   'Chimney feet meet only the rear upper-dormer/roof junction')
        permit(roof, 'turret-cap', 29, 44,
               'Original corner turret cap owns the wing roof/corner joint',
               [1, 29, 1, 12, 44, 14])
        permit(roof, 'turret-finial', 39, 46,
               'Source crown platform meets the corner roof immediately below its ornaments',
               [7, 39, 8, 13, 46, 16])
        for source in ('balcony-lower-', 'balcony-upper-', 'cornice-', 'base-arcade-', 'bay-noble-'):
            for target, y0, y1 in (('turret-base', 0, 13), ('turret-shaft', 13, 27),
                                   ('turret-cap', 27, 36)):
                # Only the old terminal column next to the relocated turret;
                # most become empty intersections after the outward move.
                permit(source + side, target, y0, y1,
                       'Source turret column owns the adjacent wing termination',
                       [0, y0, 0, 12, y1, 13])
    permit('roof-north', 'cornice-west', 29, 36,
           'West gutter owns the north roof foot at the inner corner',
           [origin, 29, 11 + origin, 10 + origin, 36, 23 + origin])
    # Export ownership follows the final writer. A west dormer cuts both the
    # west roof and the earlier north roof where their slopes cross, and the
    # north dormer likewise cuts the crossing west slope. Authorize these
    # same construction joints only inside the orthogonal inner roof region.
    for before, other in (('roof-north', 'west'), ('roof-west', 'north')):
        for grade in ('lower', 'upper', 'pavilion'):
            y0, y1 = (31, 38) if grade == 'lower' else (36, 43)
            permit(before, 'dormer-' + grade + '-' + other, y0, y1,
                   'Source dormer owns the crossing wing roof only inside their orthogonal roof intersection',
                   [3 + origin, y0, 11 + origin, 23 + origin, y1, 23 + origin])
        permit(before, 'chimney-' + other, 40, 46,
               'Complete ridge chimney owns its feet in the crossing roof intersection',
               [3 + origin, 40, 11 + origin, 23 + origin, 46, 23 + origin])
    permit('turret-cap', 'turret-finial', 39, 44,
           'Crown platform replaces the upper corner slope while retaining direct support',
           [6 + origin, 39, 7 + origin, 12 + origin, 44, 15 + origin])
    rules = []
    for before, after, zone, reason in zones:
        for index, first in enumerate(asm.stamps):
            if first['role'] != before:
                continue
            for last in asm.stamps[index + 1:]:
                if last['role'] != after:
                    continue
                lo = [max(zone[i], first['anchor'][i], last['anchor'][i]) for i in range(3)]
                hi = [min(zone[i + 3], first['anchor'][i] + first['size_whd'][i],
                          last['anchor'][i] + last['size_whd'][i]) for i in range(3)]
                if all(lo[i] < hi[i] for i in range(3)):
                    rule = {'from_role': before, 'to_role': after,
                            'bbox_xyz_half_open': lo + hi, 'reason': reason}
                    if rule not in rules:
                        rules.append(rule)
    return rules


def build_composed(run_dir, seed, bays_north, bays_west, composition, *, skip_render=True,
                   dry_run=False):
    """Build the grouped design and return the scene plus an assembly manifest.

    ``dry_run=True`` resolves and records every slot through this identical code path
    while writing no voxel, so the returned slot plan is what the real build would do.
    """
    validate_composition(composition)
    if composition['mode'] != 'grouped_pavilions':
        raise ValueError('build_composed requires grouped_pavilions; use original build for flat_baseline')
    if (composition['plan']['seed'] != seed
            or composition['wings']['north']['bay_count'] != bays_north
            or composition['wings']['west']['bay_count'] != bays_west):
        raise ValueError('composition seed and bay counts must match the requested build')
    run_dir = Path(run_dir).resolve()
    run_dir.relative_to(ROOT)
    run_dir.mkdir(parents=True, exist_ok=True)
    dump_json(run_dir / 'composition.json', composition)
    origin = composition['corner']['origin_margin']
    phase = composition['rhythm']['phase']
    rhythm = composition['rhythm']['pattern']
    xs = _positions(composition['wings']['north'], kit.BAY_START_NORTH, phase, rhythm)
    zs = _positions(composition['wings']['west'], kit.BAY_START_WEST, phase, rhythm)
    xw, zw = xs[-1] + 6, zs[-1] + 6
    if xw + origin > composition['plan']['width'] or zw + origin > composition['plan']['depth']:
        raise ValueError('composition including widened piers and origin margin exceeds the plan width/depth budget')
    segments = {'north': _segments(composition['wings']['north'], xs, xw, 0),
                'west': _segments(composition['wings']['west'], zs, zw, kit.BAY_START_WEST)}
    scene = Scene(xw + origin, 52, zw + origin)
    asm = Assembler(scene, run_dir / 'derived', dry_run=dry_run)
    derived = kit.derive_pieces(asm)
    derived['pavilion_w'] = _rotate(asm, 'derived:st1-dormer-pavilion@r3',
                                    'v4:st1-dormer-pavilion', 3)
    derived['chimney_cluster'] = _cut(
        asm, 'derived:st1-chimney-group@five-flue-pure', 'v4:st1-chimney-group',
        [2, 2, 4, 4, 10, 10],
        'Complete five source pot mouths plus the adjacent narrow stone rod; remove lower roof-foot courses')
    derived['chimney_cluster_n'] = _rotate(
        asm, 'derived:st1-chimney-group@five-flue-pure-r1', derived['chimney_cluster'], 1)
    derived['finial'] = _cut(
        asm, 'derived:b1-corner-pavilion-cap@crown', 'v4:b1-corner-pavilion-cap',
        [8, 16, 6, 14, 24, 14],
        'Whole source crown: stone platform, iron/chain rail, four posts and brewing-stand/chain/button ornaments')
    derived['planter'] = _cut(
        asm, 'derived:st1-corner-turret-shaft@hanging-planter', 'v4:st1-corner-turret-shaft',
        [4, 9, 1, 6, 13, 4],
        'Whole source hanging planter with two frozen pumpkin stems, granite/hay box and oak-trapdoor rain cover')
    derived['planter_w'] = _rotate(
        asm, 'derived:st1-corner-turret-shaft@hanging-planter-r3', derived['planter'], 3)
    for grade, parent, height, depth in (
            ('noble', 'v4:st1-window-bay-noble', 13, 7),
            ('standard', 'v4:st1-window-bay-standard', 6, 4)):
        for side_name, left in (('left', 0), ('right', 3)):
            key = 'pier_' + grade + '_' + side_name
            derived[key] = _cut(
                asm, 'derived:st1-window-bay-%s@%s-half-pier' % (grade, side_name), parent,
                [left, 0, 0, left + 1, height, depth],
                'Source one-cell side half-pier; no glass or invented window variant')
            derived[key + '_w'] = _rotate(asm, derived[key] + '-r3', derived[key], 3)
    tops = kit.slope_tops(asm, derived['roof'])
    fill = _fill(asm, xs, zs, (xw, zw), segments, origin, tops, dry_run=dry_run)
    fill['roof_backing_cells'] = _roof_backing(asm, derived, segments, origin)

    def stamp(ident, x, y, z, role):
        return asm.stamp(ident, x + origin, y, z + origin, role=role)

    def bands(key, side, y, front, role, roof=False):
        ident = derived[key + ('_w' if side == 'west' else '')]
        for segment in segments[side]:
            lo = segment['roof_lo'] if roof else segment['lo']
            hi = segment['hi']
            if roof and segment is segments[side][-1]:
                hi -= 1  # The reserved terminal line belongs to the dark end shell.
            p = segment['projection']
            if side == 'north':
                kit.tile_piece(asm, ident, lo + origin, hi + origin,
                               0, y, front - p + origin, role)
            else:
                kit.tile_piece(asm, ident, lo + origin, hi + origin,
                               front - p + origin, y, 0, role, axis='z')

    bands('roof', 'north', kit.Y_ROOF, kit.COMMON_Z, 'roof-north', True)
    bands('roof', 'west', kit.Y_ROOF, 3, 'roof-west', True)
    for side in ('north', 'west'):
        bands('balcony', side, kit.Y_BALCONY, 1, 'balcony-lower-' + side)
        bands('balcony', side, kit.Y_BALCONY_UP, 1, 'balcony-upper-' + side)
        bands('cornice', side, kit.Y_CORNICE, 0, 'cornice-' + side)
        ident = 'v4:st1-base-arcade' if side == 'north' else derived['arcade_w']
        for segment in segments[side]:
            front = 3 - segment['projection'] + origin
            kit.tile_piece(asm, ident, segment['lo'] + origin, segment['hi'] + origin,
                           0 if side == 'north' else front, 0,
                           front if side == 'north' else 0,
                           'base-arcade-' + side, axis='x' if side == 'north' else 'z')
        for bay, axis in zip(composition['wings'][side]['bays'], xs if side == 'north' else zs):
            p = bay['projection']
            if side == 'north':
                stamp('v4:st1-window-bay-noble', axis, kit.Y_NOBLE, 1 - p, 'bay-noble-north')
                stamp('v4:st1-window-bay-standard', axis, kit.Y_STANDARD, 4 - p, 'bay-standard-north')
            else:
                stamp(derived['noble_w'], 1 - p, kit.Y_NOBLE, axis, 'bay-noble-west')
                stamp(derived['standard_w'], 4 - p, kit.Y_STANDARD, axis, 'bay-standard-west')
        positions = xs if side == 'north' else zs
        for index, before in enumerate(positions):
            after = positions[index + 1] if index + 1 < len(positions) else (xw if side == 'north' else zw)
            left_p = composition['wings'][side]['bays'][index]['projection']
            right_p = (composition['wings'][side]['bays'][index + 1]['projection']
                       if index + 1 < len(positions) else left_p)
            for axis in range(before + 4, after):
                first = axis == before + 4
                p = left_p if first else right_p
                source_side = 'right' if first else 'left'
                for grade, y, front in (('noble', kit.Y_NOBLE, 1), ('standard', kit.Y_STANDARD, 4)):
                    ident = derived['pier_' + grade + '_' + source_side + ('_w' if side == 'west' else '')]
                    if side == 'north':
                        stamp(ident, axis, y, front - p, 'pier-' + grade + '-north')
                    else:
                        stamp(ident, front - p, y, axis, 'pier-' + grade + '-west')
    corner_delta = -composition['corner']['projection']
    stamp('v4:st1-corner-turret-base', corner_delta, 0, 1 + corner_delta, 'turret-base')
    stamp('v4:st1-corner-turret-shaft', corner_delta, kit.Y_SHAFT, 1 + corner_delta, 'turret-shaft')
    stamp(derived['cap'], 1 + corner_delta, kit.Y_CAP, 1 + corner_delta, 'turret-cap')
    # Platform y39 sits directly on the existing cap's y38 upper slope; its contact
    # count is recorded before placement instead of assuming support.
    #
    # Contact is computed from the cap PIECE's own cells rather than by reading the scene
    # back. Reading the scene made this check depend on draw order and made a dry run
    # impossible (an empty scene reports zero contact and raises). Deriving it from the
    # piece is exact, order-independent, and identical in both modes.
    finial_anchor = [6 + origin, 39, 7 + origin]
    crown = _read(asm, derived['finial'])
    cap_read = _read(asm, derived['cap'])
    cap_anchor = (1 + corner_delta, kit.Y_CAP, 1 + corner_delta)
    cap_cells = {
        (cap_anchor[0] + dx, cap_anchor[1] + dy, cap_anchor[2] + dz)
        for dy in range(cap_read.volume.shape[0])
        for dz in range(cap_read.volume.shape[1])
        for dx in range(cap_read.volume.shape[2])
        if int(cap_read.volume[dy, dz, dx]) not in cap_read.air_ids}
    contact = sum(
        (finial_anchor[0] + dx, 38, finial_anchor[2] + dz) in cap_cells
        for dz in range(crown.volume.shape[1]) for dx in range(crown.volume.shape[2])
        if int(crown.volume[0, dz, dx]) not in crown.air_ids)
    if not contact:
        raise ValueError('source crown platform must contact the corner cap')
    asm.stamp(derived['finial'], *finial_anchor, role='turret-finial')
    for side in ('north', 'west'):
        wing = composition['wings'][side]
        positions = xs if side == 'north' else zs
        for bay, axis in zip(wing['bays'], positions):
            if bay['dormer_grade'] == 'none':
                continue
            p = bay['projection']
            if side == 'north':
                stamp('v4:st1-dormer-lower', axis, kit.Y_DORMER_LO, 5 - p, 'dormer-lower-north')
                ident = 'v4:st1-dormer-pavilion' if p else 'v4:st1-dormer-upper'
                stamp(ident, axis - int(bool(p)), kit.Y_DORMER_HI, 7 - p,
                      'dormer-pavilion-north' if p else 'dormer-upper-north')
            else:
                stamp(derived['dormer_lo_w'], 5 - p, kit.Y_DORMER_LO, axis, 'dormer-lower-west')
                ident = derived['pavilion_w'] if p else derived['dormer_hi_w']
                stamp(ident, 7 - p, kit.Y_DORMER_HI, axis - int(bool(p)),
                      'dormer-pavilion-west' if p else 'dormer-upper-west')
        for anchor in wing['chimney_anchors']:
            axis = positions[anchor['bay']]
            p = wing['bays'][anchor['bay']]['projection']
            if side == 'north':
                stamp(derived['chimney_cluster_n'], axis - 1, 40, 14 - p, 'chimney-north')
            else:
                stamp(derived['chimney_cluster'], 14 - p, 40, axis - 1, 'chimney-west')
        for bay, axis in zip(wing['bays'], positions):
            if not bay['plant_accent']:
                continue
            p = bay['projection']
            if side == 'north':
                stamp(derived['planter'], axis + 1, 19, 1 - p, 'plant-noble-north')
            else:
                stamp(derived['planter_w'], 1 - p, 19, axis + 1, 'plant-noble-west')

    if dry_run:
        # Everything above resolved every slot through the real code path; nothing below
        # can run, because export, read-back and the stamp audit all need actual voxels.
        return scene, {
            'run': run_dir.name, 'seed': seed, 'dry_run': True,
            'composition': composition,
            'rhythm': {'pattern': rhythm, 'phase': phase,
                       'bay_start_north': kit.BAY_START_NORTH, 'bay_start_west': kit.BAY_START_WEST},
            'scene': {'width': xw + origin, 'height': 52, 'depth': zw + origin,
                      'bays_north': [x + origin for x in xs], 'bays_west': [z + origin for z in zs]},
            'segments': segments,
            'stamps': asm.stamps,
            'derived_pieces': asm.derived,
            'fill': {**fill, 'material': kit.FILL, 'party_joint': kit.FILL_JOINT},
            # The scene is intentionally empty in a dry run; reporting a voxel count here
            # would invite a reader to believe geometry was written.
            'scene_nonair_cells': 0,
        }

    schem_path = run_dir / 'ATLAS-HOUSE.schem'
    export_info = write_schematic(schem_path, scene.volume, scene.palette, name=NAME)
    read_back = load_schematic(schem_path)
    validation = read_back.validation()
    registry = validate_vanilla(schem_path)
    policy = _junction_policy(asm, xw + origin, zw + origin, origin)
    audit = library.verify_stamp_audit(read_back, asm.audit_entries(), asm.audit_rows(),
                                       allow_overwrites=True, allowed_overwrites=policy)
    chimney_read = _read(asm, derived['chimney_cluster'])
    mouths = sum(int(np.count_nonzero(chimney_read.volume == index))
                 for index, value in enumerate(chimney_read.id_to_state)
                 if split_state(value)[0] == 'minecraft:flower_pot')
    if mouths != 5:
        raise ValueError('source-backed chimney subcut must retain five pot mouths')
    def primitive_sources(ident):
        if ident in asm.derived:
            return primitive_sources(asm.derived[ident]['provenance']['source_id'])
        return {ident}
    used = sorted(set().union(*(primitive_sources(row['id']) for row in asm.stamps)))
    assembly = {
        'run': run_dir.name, 'seed': seed,
        'rhythm': {'pattern': rhythm, 'phase': phase,
                   'bay_start_north': kit.BAY_START_NORTH, 'bay_start_west': kit.BAY_START_WEST},
        'composition': composition, 'composition_execution': {
            'origin_xyz': [origin, 0, origin], 'corner_offset_from_wings': [corner_delta, 0, corner_delta],
            'segments': segments, 'crown_platform_contact_cells': int(contact),
            'chimney_mouths_per_source_cluster': mouths,
            'chimney_base_y': 40, 'chimney_top_y': 47,
            'pier_faces': 'SOURCE_WINDOW_HALF_PIERS_NO_GLASS',
            'chimney_axis': {'north': 'x', 'west': 'z'},
            'plant_strategy_status': 'SOURCE_HANGING_PLANTERS_ON_PAVILION_NOBLE_BAYS',
            'window_grade_status': 'PROJECTION_AND_WIDENED_PIERS_ONLY_NO_INVENTED_WINDOW_VARIANT',
        },
        'common_origin_subtracted': [kit.COMMON_X, kit.COMMON_Y, kit.COMMON_Z],
        'scene': {'width': xw + origin, 'height': 52, 'depth': zw + origin,
                  'bays_north': [x + origin for x in xs], 'bays_west': [z + origin for z in zs]},
        'schematic': {'path': str(schem_path.relative_to(ROOT)), **export_info},
        'piece_sources': [piece_source(ident) for ident in used],
        'excluded_pieces': [], 'derived_pieces': asm.derived, 'stamps': asm.stamps,
        'fill': {**fill, 'material': kit.FILL, 'party_joint': kit.FILL_JOINT,
                 'firewall_policy': 'TRUE_SOURCE_SLOPE_DARK_RESERVED_END_SHELL_BEFORE_STAMPS',
                 'roof_end_shell': {'material': 'minecraft:deepslate_tiles', 'reserved_axis_width': 1}},
        'overwrites': {'counts': {k: int(v) for k, v in scene.overwrite_counts.items()},
                       'samples': scene.overwrite_samples},
        'stamp_audit': audit, 'validation': validation, 'independent_registry': registry,
        'source_trace': {'status': 'PASS', 'verified_stamps': len(asm.stamps),
                         'derived_pieces': len(asm.derived),
                         'policy': 'original source hash + original frozen states + replayed declared operations',
                         'door_policy': 'PRESERVE_SOURCE_HALF_STATES', 'game_acceptance': 'NOT_RUN'},
    }
    if not skip_render and all(assembly[key]['status'] == 'PASS' for key in
                               ('validation', 'independent_registry', 'source_trace', 'stamp_audit')):
        assembly['renders'] = kit.render(schem_path, run_dir / 'previews')
    dump_json(run_dir / 'assembly.json', assembly)
    print('composed:', validation['status'], '| audit:', audit['status'],
          '| unexplained:', audit.get('unexplained_cells'),
          '| fully lost:', audit.get('fully_lost_stamps'))
    return scene, assembly
