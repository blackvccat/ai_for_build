"""North/west atlas stage predicates measured in the final exported schematic.

Frame specifications are targets and search regions, never observations. Both
bare frames and dressed stages retain these massing obligations. Source stamp
audits and the amount of detail cannot repair a missing wing, blind wall, corner
projection or roof profile. Partial model visibility remains explicitly scoped.
"""
from collections import Counter, deque
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import numpy as np

from . import architectural_conformance as core
from .architecture import split_state
from .schematic import AIR_BLOCKS, base_block, load_schematic


POLICY_ID = 'export-atlas-nw-stage-v1'
FRAME_STAGES = {'frameworks', 'framework', 'massing'}
DETAIL_STAGES = {'facades', 'tier2', 'tier3', 'delivery'}
ROOT = Path(__file__).resolve().parents[2]
FRAME_KEYS = {'schema_version', 'stage', 'bounds_xyz_half_open',
              'occupied_envelope_upper_xyz', 'origin_xyz', 'wing_segments',
              'street_faces', 'party_faces', 'roof_profile',
              'roof_junction_zone_xyz_half_open', 'roof_joint_bbox_xyz_half_open',
              'corner', 'openings', 'fixed_levels', 'balcony_baselines', 'limitations',
              'roof_accessory_bboxes'}
FULL_CUBES = {
    'minecraft:sandstone', 'minecraft:smooth_sandstone', 'minecraft:cut_sandstone',
    'minecraft:chiseled_sandstone', 'minecraft:diorite', 'minecraft:andesite',
    'minecraft:stone', 'minecraft:stone_bricks', 'minecraft:mossy_stone_bricks',
    'minecraft:cracked_stone_bricks', 'minecraft:quartz_block', 'minecraft:calcite',
    'minecraft:bone_block', 'minecraft:tuff', 'minecraft:blackstone',
    'minecraft:deepslate', 'minecraft:cobbled_deepslate', 'minecraft:deepslate_bricks',
    'minecraft:deepslate_tiles', 'minecraft:polished_deepslate',
    'minecraft:cracked_deepslate_bricks', 'minecraft:cracked_deepslate_tiles',
    'minecraft:cobblestone', 'minecraft:stripped_birch_wood',
    'minecraft:stripped_oak_wood', 'minecraft:brown_mushroom_block', 'minecraft:hay_block',
    'minecraft:gray_concrete', 'minecraft:gray_concrete_powder',
    'minecraft:light_gray_concrete_powder', 'minecraft:cyan_terracotta',
    'minecraft:gray_wool', 'minecraft:polished_basalt', 'minecraft:smooth_basalt',
    'minecraft:rooted_dirt', 'minecraft:deepslate_coal_ore',
}


def _tool():
    path = ROOT / 'tools' / 'verify_atlas_composition.py'
    spec = importlib.util.spec_from_file_location('paris_builder_atlas_measurement_tool', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bbox(value):
    return (isinstance(value, list) and len(value) == 6 and all(type(v) is int for v in value)
            and all(0 <= value[i] < value[i + 3] for i in range(3)))


def _opaque(name):
    return isinstance(name, str) and (name in FULL_CUBES or name.endswith('_planks'))


def _intersection(first, second):
    result = [max(first[i], second[i]) for i in range(3)] + [min(first[i + 3], second[i + 3]) for i in range(3)]
    return result if all(result[i] < result[i + 3] for i in range(3)) else None


def _components(points):
    remaining = set(map(tuple, points))
    result = []
    while remaining:
        seed = remaining.pop()
        pending, component = deque([seed]), {seed}
        while pending:
            x, y, z = pending.popleft()
            for other in ((x-1,y,z), (x+1,y,z), (x,y-1,z), (x,y+1,z), (x,y,z-1), (x,y,z+1)):
                if other in remaining:
                    remaining.remove(other)
                    component.add(other)
                    pending.append(other)
        result.append(component)
    return result


def _outward(value, wing):
    if value in ('-z', 'north', 2) or value == [0, 0, -1]:
        return 2, -1
    if value in ('-x', 'west', 0) or value == [-1, 0, 0]:
        return 0, -1
    if value is None and wing in ('north', 'west'):
        return (2, -1) if wing == 'north' else (0, -1)
    return None


def _native_window_targets(opening, cells, outward):
    """Translate this kit's abstract glass plane into its actual frozen leaves.

    These are the observed st1 window conventions, not general Minecraft door
    rules: all source window leaves have half=lower and open=false, including
    rows stacked without an ordinary door upper half. The west wing is a true
    rotation of the north piece, while the turret's west face is a native source
    face with the opposite hinge order. The noble lower sill starts one cell
    behind the remaining front leaves. Unknown roles/layouts stay unsupported.
    """
    role = opening.get('role')
    corner = bool(opening.get('corner'))
    prefix = 'corner_' if corner else ''
    if role not in {prefix + grade for grade in ('standard', 'noble_lower', 'noble_upper')}:
        return None
    normal, _ = outward
    axis = 0 if normal == 2 else 2
    levels = {}
    for point in cells:
        levels.setdefault(point[1], []).append(point)
    rows = [sorted(row, key=lambda point: point[axis]) for _, row in sorted(levels.items())]
    if any(len(row) != 2 or row[1][axis] != row[0][axis] + 1
           or row[0][normal] != row[1][normal] for row in rows):
        return None
    if len({tuple(point[axis] for point in row) for row in rows}) != 1:
        return None
    fronts = [row[0][normal] for row in rows]
    rear_sill = role == 'noble_lower' and not corner
    if rear_sill:
        if len(rows) < 2 or len(set(fronts[1:])) != 1 or fronts[0] != fronts[1] + 1:
            return None
    elif len(set(fronts)) != 1:
        return None
    faces = ('east', 'west') if normal == 2 else ('south', 'north')
    hinges = ('right', 'left') if normal == 2 or corner else ('left', 'right')
    targets = []
    for index, row in enumerate(rows):
        rear_sill = role == 'noble_lower' and not corner and index == 0
        for column, point in enumerate(row):
            member = 1 - column if rear_sill else column
            properties = {'facing': faces[member], 'hinge': hinges[member],
                          'half': 'lower', 'open': 'false', 'powered': 'false'}
            if role == 'corner_noble_upper' and normal == 0 and column == 1:
                # This native turret face deliberately freezes both leaves
                # with a right hinge; it is not the rotated main-wing pair.
                properties['hinge'] = 'right'
            targets.append((point, 'minecraft:iron_door', properties))
    return targets


def _native_roof_edges(measured, box, side, mineral_names, wall_names):
    """Actual supported, horizontal low-wall roof courses of the st1 section.

    Match frozen geometry rather than promoting every dark wall to roof: the
    source's d4/d6/d8 edges have no central post, two low tangent arms, no normal
    arms, and a classified mineral course immediately below. Dormer cheeks and
    chimney rods do not satisfy this state-and-support rule.
    """
    along, normal = (('east', 'west'), ('north', 'south')) if side == 'north' else (
        ('north', 'south'), ('east', 'west'))
    result = []
    for point in measured.points(box, wall_names):
        x, y, z = point
        _, properties = split_state(measured.read.id_to_state[int(measured.volume[y, z, x])])
        supported = measured.state(x, y - 1, z) in mineral_names
        if (supported and properties.get('up') == 'false' and properties.get('waterlogged') == 'false'
                and all(properties.get(key) == 'low' for key in along)
                and all(properties.get(key) == 'none' for key in normal)):
            result.append(point)
    return result


def measure(schematic, plan=None, section=None, *, stage=None):
    path = Path(schematic)
    raw_plan = plan or {}
    stage = stage or (raw_plan.get('_stage') if isinstance(raw_plan, dict) else None) or 'facades'
    plan = core._plan(raw_plan)
    read = load_schematic(path)
    source = {'path': str(path.resolve()), 'sha256': sha256(path.read_bytes()).hexdigest(),
              'voxel_state_hash': read.voxel_state_hash()}
    if section is not None and any(section.get('source', {}).get(key) != source[key]
                                   for key in ('sha256', 'voxel_state_hash')):
        raise ValueError('Section evidence is stale or belongs to another atlas export')
    tool = _tool()
    measured = tool.Measurement(read, [])
    checks = []

    def add(ident, status, observation, expected=None, actual=None, coordinates=None, *, required=True, scope='atlas_export_voxels'):
        checks.append({'id': ident, 'status': status, 'required': required,
                       'observation': observation, 'reason': observation, 'expected': expected,
                       'actual': actual, 'coordinates': coordinates or {}, 'scope': scope})

    spec = plan.get('atlas_frame_spec')
    schema = isinstance(spec, dict) and spec.get('schema_version') == 1
    add('atlas/spec', 'pass' if schema else 'unsupported',
        'Atlas stages require an explicit version-1 north/west frame target; an implementation manifest is not geometry evidence.',
        {'schema_version': 1}, {'schema_version': spec.get('schema_version') if isinstance(spec, dict) else None})
    if not schema:
        spec = {}
    for key in sorted(set(spec) - FRAME_KEYS):
        add('atlas/spec/' + key, 'unsupported', 'No implemented predicate for the additional frame target: ' + key, spec[key])
    stage_known = stage in FRAME_STAGES | DETAIL_STAGES
    add('atlas/stage', 'pass' if stage_known else 'unsupported',
        'Current stage determines obligations; framework geometry is checked before any source-detail obligations.',
        sorted(FRAME_STAGES | DETAIL_STAGES), stage)
    # Atelier reviews atlas massing twice before any source detail enters: at
    # frameworks and again at facades. A facade-stage export whose hash-bound plan
    # still declares bare massing carries framework obligations, not native-leaf
    # ones. The exemption cannot leak into detail stages: tier2/tier3 builds fail
    # their technical gate unless the manifest declares post_framework_complete_kit,
    # and a bare claim there would contradict the declared kit contract.
    bare = stage in FRAME_STAGES or (stage == 'facades'
                                     and plan.get('atlas_tier_semantics') == 'bare_massing')
    bounds = spec.get('bounds_xyz_half_open')
    valid_bounds = _bbox(bounds) and bounds[:3] == [0, 0, 0]
    expected_size = [bounds[i + 3] - bounds[i] for i in range(3)] if valid_bounds else None
    actual_size = [read.width, read.height, read.length]
    positions = np.argwhere(~np.isin(read.volume, measured.air_ids))
    actual_upper = ([int(positions[:, 2].max()) + 1, int(positions[:, 0].max()) + 1,
                     int(positions[:, 1].max()) + 1] if len(positions) else None)
    upper_target = spec.get('occupied_envelope_upper_xyz') if bare else (bounds[3:] if valid_bounds else None)
    valid_upper = isinstance(upper_target, list) and len(upper_target) == 3 and all(type(v) is int for v in upper_target)
    fit = (valid_bounds and valid_upper and actual_size == expected_size and actual_upper is not None
           and all(actual_upper[i] <= upper_target[i] for i in range(3)))
    add('atlas/bounds', 'unsupported' if not valid_bounds or not valid_upper else 'pass' if fit else 'fail',
        'Read container dimensions and actual occupied upper envelope from the export; details may rise only inside the stage bounds.',
        {'dimensions_whd': expected_size, 'occupied_upper_xyz': upper_target},
        {'dimensions_whd': actual_size, 'occupied_upper_xyz': actual_upper})

    segments = spec.get('wing_segments', [])
    segment_valid = isinstance(segments, list) and bool(segments) and all(
        isinstance(row, dict) and row.get('wing') in ('north', 'west')
        and _bbox(row.get('body_bbox_xyz_half_open')) and _bbox(row.get('roof_bbox_xyz_half_open'))
        for row in segments)
    if not segment_valid:
        segments = []
        add('atlas/wings/schema', 'unsupported', 'Both wing segments require explicit body and roof search boxes.')
    streets = spec.get('street_faces')
    street_valid = isinstance(streets, list) and set(streets) in ({'north', 'west'}, {'street_north', 'street_west'})
    add('atlas/topology/north_west_streets', 'pass' if street_valid and {row['wing'] for row in segments} == {'north', 'west'} else 'unsupported',
        'The controlled adapter measures north and west body envelopes and east/south blind skins; this is a declared use policy with export checks below.',
        ['north', 'west'], streets, scope='declared_roles_with_measured_envelopes')
    for index, row in enumerate(segments):
        box = row['body_bbox_xyz_half_open']
        points = measured.points(box)
        total = (box[3]-box[0]) * (box[4]-box[1]) * (box[5]-box[2])
        fraction = len(points) / total
        normal = 2 if row['wing'] == 'north' else 0
        front = min((point[normal] for point in points), default=None)
        base_front, wall_front = row.get('base_front', box[normal]), row.get('wall_front')
        target_front_known = type(base_front) is int and type(wall_front) is int
        good = fraction >= .75 and target_front_known and front is not None and base_front <= front <= wall_front
        add('atlas/body/' + str(index), 'unsupported' if not target_front_known else 'pass' if good else 'fail',
            'The actual wing body must occupy at least 75% of its declared mass box and retain its north/west street envelope. Ornament counts do not enter this check.',
            {'wing': row['wing'], 'minimum_occupied_fraction': .75, 'front_range': [base_front, wall_front]},
            {'occupied_cells': len(points), 'total_cells': total, 'occupied_fraction': fraction, 'actual_front': front},
            {'bbox_xyz_half_open': box})

    joints = [_intersection(n['body_bbox_xyz_half_open'], w['body_bbox_xyz_half_open'])
              for n in segments if n['wing'] == 'north' for w in segments if w['wing'] == 'west']
    joints = [box for box in joints if box]
    joint_points = {tuple(point) for box in joints for point in measured.points(box)
                    if _opaque(measured.state(*point))}
    joint_total = len({(x, y, z) for box in joints for x in range(box[0], box[3])
                       for y in range(box[1], box[4]) for z in range(box[2], box[5])})
    parts = _components(joint_points)
    largest = max(map(len, parts), default=0)
    joint_good = joint_total > 0 and largest / joint_total >= .5
    add('atlas/junctions/wing_body', 'unsupported' if not joints else 'pass' if joint_good else 'fail',
        'A single face-connected opaque body component must occupy at least half the actual north/west joint zone; no source-audit status is reused.',
        {'minimum_connected_fraction': .5}, {'joint_cells': joint_total, 'opaque_cells': len(joint_points),
                                           'largest_connected_component': largest}, {'intersection_boxes': joints})

    party_faces = spec.get('party_faces', [])
    if not isinstance(party_faces, list) or not party_faces:
        add('atlas/party/schema', 'unsupported', 'Explicit blind party-skin search planes are required.')
        party_faces = []
    for index, row in enumerate(party_faces):
        box = row.get('bbox_xyz_half_open', row.get('surface_bbox_xyz_half_open')) if isinstance(row, dict) else None
        if not _bbox(box):
            add('atlas/party/' + str(index), 'unsupported', 'The party skin requires a valid surface bbox.')
            continue
        bad, unknown, sampled = [], [], 0
        for x in range(box[0], box[3]):
            for y in range(box[1], box[4]):
                for z in range(box[2], box[5]):
                    sampled += 1
                    name = measured.state(x, y, z)
                    if name is None or name in AIR_BLOCKS or 'glass' in name or name.endswith('_door'):
                        bad.append([x, y, z])
                    elif not _opaque(name):
                        unknown.append({'xyz': [x, y, z], 'block': name})
        add('atlas/party/' + str(index), 'fail' if bad else 'unsupported' if unknown else 'pass',
            'Sample every declared east/south blind-skin cell, including plate heights; air, glass or door states fail. Unknown partial models remain unsupported.',
            'opaque full-cube skin', {'sampled_cells': sampled, 'violations': len(bad), 'unknown_models': len(unknown)},
            {'bbox_xyz_half_open': box, 'violations_xyz': bad[:40], 'unknown_samples': unknown[:20]})

    corner = spec.get('corner', {})
    corner_box = corner.get('body_bbox_xyz_half_open') if isinstance(corner, dict) else None
    corner_points = measured.points(corner_box) if _bbox(corner_box) else []
    body_fronts = {}
    for side, normal in (('north', 2), ('west', 0)):
        observed = [c['actual']['actual_front'] for c in checks if c['id'].startswith('atlas/body/')
                    and isinstance(c.get('expected'), dict) and c['expected'].get('wing') == side
                    and c.get('actual', {}).get('actual_front') is not None]
        body_fronts[side] = max(observed, default=None)
    actual_corner = {'min_x': min((p[0] for p in corner_points), default=None),
                     'min_z': min((p[2] for p in corner_points), default=None)}
    target_projection = plan.get('composition', {}).get('corner', {}).get('projection')
    projection_known = type(target_projection) is int and _bbox(corner_box)
    advances = {side: (body_fronts[side] - actual_corner['min_z' if side == 'north' else 'min_x']
                      if body_fronts[side] is not None and actual_corner['min_z' if side == 'north' else 'min_x'] is not None else None)
                for side in ('north', 'west')}
    corner_good = bool(corner_points) and all(value is not None and value >= target_projection for value in advances.values()) if projection_known else False
    add('atlas/corner/body_projection', 'unsupported' if not projection_known else 'pass' if corner_good else 'fail',
        'The actual corner body must advance at least the requested distance beyond both wing street envelopes; a finial cannot substitute for the body.',
        {'minimum_projection': target_projection}, {**actual_corner, 'actual_advance_from_wings': advances},
        {'body_bbox_xyz_half_open': corner_box})
    cap_box = corner.get('cap_bbox_xyz_half_open') if isinstance(corner, dict) else None
    cap_target = corner.get('cap_top_y') if isinstance(corner, dict) else None
    cap_points = measured.points(cap_box) if _bbox(cap_box) else []
    cap_top = max((point[1] for point in cap_points), default=None)
    cap_known = _bbox(cap_box) and type(cap_target) is int
    add('atlas/corner/control_height', 'unsupported' if not cap_known else 'pass' if cap_top == cap_target else 'fail',
        'Read the actual highest corner-control voxel. Bare massing expresses the cap volume; detailed stages may express its final crown. The body obligation stays separate.',
        {'top_y': cap_target}, {'actual_top_y': cap_top}, {'cap_bbox_xyz_half_open': cap_box})

    locator_path = path.parent / 'assembly.json'
    locator_rows, locator_hash = [], None
    if not bare and locator_path.is_file():
        locator_bytes = locator_path.read_bytes()
        locators = json.loads(locator_bytes)
        locator_rows = locators.get('stamps', [])
        locator_hash = sha256(locator_bytes).hexdigest()
    exclusions = [tool._box(row) for row in locator_rows
                  if row.get('role', '').startswith(('dormer-', 'chimney-', 'turret-'))]
    if bare:
        for accessory in spec.get('roof_accessory_bboxes', []):
            box = accessory.get('bbox_xyz_half_open') if isinstance(accessory, dict) else None
            if _bbox(box):
                exclusions.append(box)
            else:
                add('atlas/roof/accessory_schema/' + str(len(exclusions)), 'unsupported',
                    'A declared roof accessory must have a valid bounded search box.')
    junction = spec.get('roof_junction_zone_xyz_half_open', spec.get('roof_joint_bbox_xyz_half_open'))
    if _bbox(junction):
        exclusions.append(junction)

    def excluded(point):
        # A replaced accessory column cannot reveal the underlying roof top:
        # ignoring only its high voxels would mistake the surviving low stub
        # for a roof surface. Exclude the whole x/z column from this sampler.
        return any(box[0] <= point[0] < box[3] and box[2] <= point[2] < box[5]
                   for box in exclusions)

    profile = spec.get('roof_profile', {})
    profile_tops = profile.get('top_y_by_depth', profile.get('depth_local_top_y')) if isinstance(profile, dict) else None
    datum = profile.get('datum_y') if isinstance(profile, dict) else None
    profile_known = isinstance(profile_tops, list) and len(profile_tops) >= 4 and type(datum) is int
    for side in ('north', 'west'):
        samples = {}
        selected = [row for row in segments if row['wing'] == side and row.get('role') in
                    ('near_recess', 'middle_recess', 'recessed', 'flat')]
        if not selected:
            selected = [row for row in segments if row['wing'] == side]
        for row in selected:
            box, front = row['roof_bbox_xyz_half_open'], row.get('roof_front')
            if type(front) is not int:
                continue
            axis, normal = (0, 2) if side == 'north' else (2, 0)
            columns = {}
            roof_points = measured.points(box, tool.ROOF_MINERALS)
            if not bare:
                roof_points += _native_roof_edges(measured, box, side, tool.ROOF_MINERALS, tool.DARK_CHEEKS)
            for point in roof_points:
                if excluded(point):
                    continue
                key = (point[axis], point[normal] - front)
                columns[key] = max(columns.get(key, -1), point[1])
            for (_, depth), top in columns.items():
                samples.setdefault(depth, []).append(top)
        observations, bad, absent = [], [], []
        for depth, target in enumerate(profile_tops or []):
            if target is None:
                continue
            actual = Counter(samples.get(depth, [])).most_common(1)
            top = actual[0][0] if actual else None
            expected = datum + target if profile_known and type(target) is int else None
            observations.append({'depth': depth, 'expected_top_y': expected, 'actual_modal_top_y': top,
                                 'sampled_columns': len(samples.get(depth, []))})
            if top is None:
                absent.append(depth)
            elif top != expected:
                bad.append(depth)
        shape = len({row['actual_modal_top_y'] for row in observations if row['actual_modal_top_y'] is not None}) >= 3
        status = ('unsupported' if not profile_known or not observations else 'fail' if bad or not shape
                  else 'unsupported' if absent else 'pass')
        add('atlas/roof/profile/' + side, status,
            'Measure modal actual mineral-roof and supported, directional frozen low-wall edge tops by normalized depth outside source accessories and the corner junction. At least three roof levels must survive; a flat shell cannot pass.',
            {'datum_y': datum, 'top_y_by_depth': profile_tops}, {'profile': observations, 'mismatched_depths': bad,
                                                                     'unmeasured_depths': absent, 'three_or_more_levels': shape})
    if _bbox(junction):
        points = measured.points(junction, tool.ROOF_MINERALS | tool.DARK_CHEEKS)
        components = _components(points)
        bridged = any(any(p[0] == junction[3]-1 for p in component)
                      and any(p[2] == junction[5]-1 for p in component) for component in components)
        add('atlas/junctions/wing_roofs', 'pass' if bridged else 'fail',
            'Within the declared joint zone, one actual classified roof component must reach both wing attachment boundaries.',
            'one face-connected roof component reaching both boundaries',
            {'roof_cells': len(points), 'components': len(components), 'bridges_both_wings': bridged},
            {'bbox_xyz_half_open': junction}, scope='classified_roof_voxel_connectivity')
    else:
        add('atlas/junctions/wing_roofs', 'unsupported', 'A bounded roof junction target is required.')

    openings = spec.get('openings')
    if not isinstance(openings, list) or not openings:
        add('atlas/openings/schema', 'unsupported', 'Actual glazing placements require explicit stage-scoped opening targets.')
        openings = []
    for index, opening in enumerate(openings):
        if not isinstance(opening, dict):
            add('atlas/opening/' + str(index), 'unsupported', 'Opening target must be an object.')
            continue
        if not bare and opening.get('stage_scope') == 'bare_massing':
            continue
        cells = opening.get('glass_cells_xyz')
        outward = _outward(opening.get('outward_axis', opening.get('outward')), opening.get('wing'))
        box = opening.get('bbox_xyz_half_open')
        known = isinstance(cells, list) and bool(cells) and all(isinstance(q, list) and len(q) == 3
                   and all(type(v) is int for v in q) for q in cells) and _bbox(box) and outward is not None
        targets = None if bare or not known else _native_window_targets(opening, cells, outward)
        if not bare and targets is None:
            known = False
        missing, blocked, partial, native_contacts = [], [], [], []
        if known:
            axis, direction = outward
            for surface_index, point in enumerate(cells if bare else [item[0] for item in targets]):
                name = measured.state(*point)
                if bare:
                    valid_surface = name is not None and 'glass' in name
                    target = 'glass'
                else:
                    _, expected_name, expected_properties = targets[surface_index]
                    raw_state = (read.id_to_state[int(read.volume[point[1], point[2], point[0]])]
                                 if name is not None else '')
                    actual_name, actual_properties = split_state(raw_state)
                    valid_surface = actual_name == expected_name and all(
                        actual_properties.get(key) == value for key, value in expected_properties.items())
                    target = {'block': expected_name, 'properties': expected_properties}
                if not valid_surface:
                    missing.append({'xyz': point, 'expected_surface': target,
                                    'actual_block': name if bare else raw_state})
                    continue
                q = list(point)
                while q[axis] > 0:
                    q[axis] += direction
                    value = measured.state(*q)
                    if value is None or value in AIR_BLOCKS or 'glass' in value:
                        continue
                    if _opaque(value):
                        native_sill = (not bare and opening.get('role') == 'noble_lower'
                                       and not opening.get('corner') and point[1] == min(p[1] for p in cells)
                                       and q[axis] == point[axis] - 1 and value == 'minecraft:cut_sandstone')
                        if native_sill:
                            # Source noble local [1/2,2,4] is its stone sill;
                            # the lower leaf sits one cell behind at local z5.
                            # This exact source joint does not authorize an
                            # arbitrary cube in the remaining window corridor.
                            native_contacts.append({'surface_xyz': point, 'sill_xyz': list(q),
                                                    'actual_block': value})
                            continue
                        blocked.append({'glass_xyz': point, 'blocker_xyz': list(q), 'actual_block': value})
                        break
                    partial.append({'glass_xyz': point, 'partial_xyz': list(q), 'actual_block': value})
        add('atlas/opening/' + str(index), 'unsupported' if not known else 'fail' if missing or blocked else 'pass',
            ('Read every target glazing cell and reject known full-cube material inserted in its outward opening corridor; frozen partial models are separately reported.'
             if bare else 'At the abstract opening axis and row, independently read this kit\'s paired frozen iron leaves and exact facing/hinge/half/open states. These source window surfaces contain no glass; known outward full-cube blockers still fail.'),
            {'target_surface_cells': len(cells) if isinstance(cells, list) else None,
             'surface_policy': 'framework_glass' if bare else 'st1_native_frozen_window_leaves'},
            {'missing_glazing': len(missing) if bare else None,
             'wrong_native_leaf_states': len(missing) if not bare else None,
             'known_full_cube_blockers': len(blocked), 'partial_model_samples': len(partial),
             'native_sill_contacts': len(native_contacts)},
            {'missing': missing[:20], 'blocked': blocked[:20], 'partial_samples': partial[:12],
             'native_sill_contacts': native_contacts},
            scope='glazing_presence_and_known_cube_blockers' if bare else 'native_window_surface_and_known_cube_blockers')
        if not bare and known and opening.get('role') == 'noble_lower' and not opening.get('corner'):
            low = min(point[1] for point in cells)
            sill_cells, wrong_sills = [], []
            for point in cells:
                if point[1] != low:
                    continue
                q = list(point)
                q[outward[0]] -= 1
                sill_cells.append(q)
                value = measured.state(*q)
                if value != 'minecraft:cut_sandstone':
                    wrong_sills.append({'xyz': q, 'actual_block': value})
            add('atlas/opening/' + str(index) + '/native_sill_contact', 'fail' if wrong_sills else 'pass',
                'The stepped native noble bottom row retains its exact cut-sandstone sill one voxel outward of each rear leaf; the remaining window corridor has no such exemption.',
                {'block': 'minecraft:cut_sandstone', 'cells': sill_cells},
                {'incorrect_sill_cells': len(wrong_sills)}, {'incorrect_sills': wrong_sills},
                scope='native_stepped_sill_voxel_adjacency')
        if partial or (not bare and known):
            add('atlas/opening/' + str(index) + '/partial_visibility', 'unsupported',
                'Opening-surface integrity and opaque-cube blockage are measured; visibility and contact through the frozen partial leaf, shutter and rail models require model rays.',
                actual={'partial_samples': len(partial)}, required=False, scope='unmeasured_model_visibility')

    if not bare:
        composition = plan.get('composition')
        if not locator_rows or not isinstance(composition, dict):
            add('atlas/source_detail/schema', 'unsupported', 'Detail stages require composition targets and stamp boxes to locate independent final-state measurements.')
        else:
            detail = tool.Measurement(read, locator_rows)
            predicates = [tool._window_planes(detail, composition), tool._dormer_cheeks(detail, composition),
                          tool._plants(detail, composition), tool._chimneys(detail, composition), *tool._crown(detail, composition)]
            for item in predicates:
                add('atlas/detail/' + item['id'], {'measured_pass': 'pass', 'measured_fail': 'fail', 'unsupported': 'unsupported'}[item['status']],
                    item['criterion'], actual=item['evidence'], scope='actual_source_detail_voxels')

    summary = core._summary(checks)
    report = {'version': core.REPORT_VERSION, 'policy_id': POLICY_ID,
              'validator_sha256': core.validator_digest(), 'section_version': section.get('version') if section else None,
              'source': source, 'plan_sha256': core.plan_hash(plan), 'stage': stage,
              'status': core._status(summary), 'summary': summary, 'checks': checks,
              'source_locator_sha256': locator_hash,
              'limitations': [
                  'North/west street and east/south party roles are target policies, then geometry is sampled in their explicit zones.',
                  'Body occupancy and voxel connectivity do not prove complete interior plans or contact between partial block models.',
                  'Bare glazing and native st1 window-leaf integrity are stage-specific controls; neither proves visibility through every frozen partial model.',
                  'Roof samples prove only the retained target profile outside accessories; detailed valleys and thin-wall apertures need model geometry.',
                  'These predicates cannot approve visual composition or user-only game acceptance.',
              ], 'unscoped_requirements': ['whole-building visual composition', 'partial-block model contact and rays',
                                            'band termination quality', 'functional interior circulation'],
              'method': 'Final export states provide observations; frame and composition provide targets; source stamp rows locate detail search boxes only.'}
    return json.loads(json.dumps(report, ensure_ascii=False))


def validate(report, schematic=None, plan=None, *, stage=None, recompute=True):
    if (not isinstance(report, dict) or report.get('version') != core.REPORT_VERSION
            or report.get('policy_id') != POLICY_ID or report.get('validator_sha256') != core.validator_digest()):
        raise ValueError('Unsupported or stale atlas architectural conformance receipt')
    checks = report.get('checks')
    if not isinstance(checks, list) or not checks or len({c.get('id') for c in checks if isinstance(c, dict)}) != len(checks):
        raise ValueError('Atlas conformance checks need unique predicate IDs')
    for check in checks:
        if (not isinstance(check, dict) or not isinstance(check.get('id'), str) or not check['id']
                or check.get('status') not in ('pass', 'fail', 'unsupported') or type(check.get('required')) is not bool
                or not isinstance(check.get('observation'), str) or not check['observation'].strip()):
            raise ValueError('Malformed atlas architectural conformance check')
    summary = core._summary(checks)
    if summary != report.get('summary') or core._status(summary) != report.get('status'):
        raise ValueError('Atlas conformance summary disagrees with independent checks')
    if schematic is not None:
        path = Path(schematic)
        read = load_schematic(path)
        if (report.get('source', {}).get('sha256') != sha256(path.read_bytes()).hexdigest()
                or report.get('source', {}).get('voxel_state_hash') != read.voxel_state_hash()):
            raise ValueError('Atlas conformance export hash changed')
    if plan is not None and report.get('plan_sha256') != core.plan_hash(plan):
        raise ValueError('Atlas conformance plan hash changed')
    if stage is not None and report.get('stage') != stage:
        raise ValueError('Atlas conformance stage changed')
    if recompute and schematic is not None and plan is not None:
        # Auxiliary NE sections are not inputs to this adapter, so their version
        # is retained without importing their geometric interpretations.
        fresh = measure(schematic, plan, stage=stage or report['stage'])
        fresh['section_version'] = report.get('section_version')
        if fresh != report:
            raise ValueError('Atlas receipt differs from independently recomputed export predicates')
    return report
