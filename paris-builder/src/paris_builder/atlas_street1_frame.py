"""Execute atlas composition as relief massing before learning fine techniques.

This is a geometric construction, not a complete source kit with detail removed.
It shares the kit's measured level order and the composed layout's bay positions,
but writes only ordinary full blocks and ordinary glass. Source-stamp checks are
not applicable. The geometry contract locates targets for independent checks;
the contract itself does not grant architectural or game acceptance.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import numpy as np

from . import atlas_street1 as kit
from .architecture import Scene
from .atlas_assembly import validate_vanilla
from .atlas_composition import validate_composition
from .atlas_street1_composed import _positions, _segments
from .exporter import dump_json, write_schematic
from .schematic import load_schematic


ROOT = kit.ROOT
NAME = 'ATLAS relief massing corner apartment'
STONE = 'minecraft:smooth_sandstone'
PLINTH = 'minecraft:stone'
ROOF = 'minecraft:deepslate_tiles'
GLASS = 'minecraft:glass'
# Source front half-section, classified as main slate/basalt/ridge geometry.
# Ornament at depths 0..2 is deliberately outside the main-roof measurement.
ROOF_TOPS = (None, None, None, 1, 7, 8, 10, 11, 13, 13,
             14, 15, 15, 15, 15, 16, 16, 16, 16, 16)
FIXED_LEVELS = {
    'arcade_base': 0, 'standard_base': 6, 'lower_balcony_source_base': 10,
    'lower_balcony_platform': 12, 'noble_base': 12, 'turret_shaft_base': 13,
    'upper_balcony_source_base': 25, 'upper_balcony_platform': 27,
    'cornice_base': 27, 'turret_cap_base': 27, 'body_top_y': 28,
    'roof_datum': 29, 'dormer_lower_base': 31, 'dormer_upper_base': 36,
    'primary_roof_top_y': 45, 'corner_control_top_y': 46,
}


def _box(scene, bbox, value, owner):
    """All persisted boxes use half-open x/y/z coordinates."""
    x0, y0, z0, x1, y1, z1 = bbox
    if x0 < x1 and y0 < y1 and z0 < z1:
        scene.box(x0, y0, z0, x1 - 1, y1 - 1, z1 - 1, value, owner)


def _oriented_box(side, axis0, axis1, y0, y1, inward0, inward1):
    if side == 'north':
        return [axis0, y0, inward0, axis1, y1, inward1]
    return [inward0, y0, axis0, inward1, y1, axis1]


def _opening(scene, openings, side, axis_cells, levels, fronts, *, role,
             bay_index=None, stage_scope='all', corner=False, facade_front=None,
             reveal_depth=None):
    """Expose declared glazing to its street, then write ordinary glass.

    The source level controls contain stepped noble sills. Each row may have
    its own nearest outward glass plane. No frozen door/slab/wall states enter
    this path. Clearing the outward ray prevents a later massing volume from
    silently hiding the window at the orthogonal roof joint.
    """
    cells = []
    for y, front in zip(levels, fronts):
        for axis in axis_cells:
            if side == 'north':
                _box(scene, [axis, y, 0, axis + 1, y + 1, front],
                     'minecraft:air', 'frame:opening-clearance')
                xyz = [axis, y, front]
            else:
                _box(scene, [0, y, axis, front, y + 1, axis + 1],
                     'minecraft:air', 'frame:opening-clearance')
                xyz = [front, y, axis]
            scene.put(*xyz, GLASS, 'frame:glazing')
            cells.append(xyz)
    array = np.asarray(cells)
    lo, hi = array.min(axis=0), array.max(axis=0) + 1
    opening = {'role': role, 'wing': side, 'bay_index': bay_index,
                     'corner': corner, 'stage_scope': stage_scope,
                     'outward': '-z' if side == 'north' else '-x',
                     'bbox_xyz_half_open': [*map(int, lo), *map(int, hi)],
                     'glass_cells_xyz': cells}
    if facade_front is not None:
        opening['facade_front'] = facade_front
        opening['reveal_depth'] = reveal_depth
    openings.append(opening)


def _source_opening(openings, side, axis_cells, levels, fronts, *, role,
                    bay_index=None, corner=False):
    """Record the native skin targets separately from recessed plain glazing.

    Source window leaves occupy their own exact measured front surface. These
    targets are neither glass writes nor permission to erase the frame reveal.
    """
    cells = [[axis, y, front] if side == 'north' else [front, y, axis]
             for y, front in zip(levels, fronts) for axis in axis_cells]
    points = np.asarray(cells)
    openings.append({'role': role, 'wing': side, 'bay_index': bay_index,
                     'corner': corner, 'stage_scope': 'source_detail',
                     'outward': '-z' if side == 'north' else '-x',
                     'bbox_xyz_half_open': [*map(int, points.min(axis=0)),
                                            *map(int, points.max(axis=0) + 1)],
                     'glass_cells_xyz': cells})


def _corner_body(scene, origin, projection):
    # A quarter-rounded turret rather than a rectangular corner box or pan-coupe.
    # Relative shift equals composed's source anchors: wings get the margin,
    # while the corner moves out by the requested projection.
    delta = origin - projection
    courses = []
    for y in range(29):
        radius = 11 if y < 6 or y in (12, 27) else (12 if y == 28 else 10)
        cells = []
        for x in range(13):
            for z in range(14):
                if (x - 10) ** 2 + (z - 11) ** 2 <= radius ** 2:
                    scene.put(x + delta, y, z + delta,
                              PLINTH if y == 0 else STONE, 'frame:corner-body')
                    cells.append([x + delta, y, z + delta])
        if y in (0, 5, 12, 26, 27, 28):
            points = np.asarray(cells)
            courses.append({'y': y, 'radius': radius, 'projection': radius - 10,
                            'bbox_xyz_half_open': [*map(int, points.min(axis=0)),
                                                   *map(int, points.max(axis=0) + 1)]})
    # The plain cap is a stepped quarter mansard volume. Its highest ordinary
    # roof block expresses the overall corner control height, not a finial.
    for y in range(29, 47):
        ratio = max(0.10, (46 - y) / 19)
        rx, rz = 10 * ratio, 12 * ratio
        for x in range(1, 13):
            for z in range(1, 16):
                dx, dz = max(0, 11 - x), max(0, 13 - z)
                if (dx / rx) ** 2 + (dz / rz) ** 2 <= 1:
                    scene.put(x + delta, y, z + delta, ROOF, 'frame:corner-cap')
    return delta, courses


def _dormer_house(scene, side, axis, wall_front, y0, width, grade, bay_index):
    """Construct cheek walls and a stepped gabled cap in front of the slope.

    The roof remains behind the dormer. Clearing a window cuts a two-cell
    recess through its front, while two side cheeks carry the projecting cap.
    Ordinary blocks deliberately express this geometry without source stamps.
    """
    begin = axis - 1 if width == 6 else axis
    front = wall_front + (1 if grade == 'lower' else 5)
    # Lower houses meet the steep pitch before the upper row begins. Extending
    # them through the upper house would erase the lower cap during excavation.
    rear = front + (4 if grade == 'lower' else 6)
    cheeks = [_oriented_box(side, begin, begin + 1, y0, y0 + 6, front, rear),
              _oriented_box(side, begin + width - 1, begin + width, y0, y0 + 6, front, rear)]
    back = _oriented_box(side, begin, begin + width, y0, y0 + 6, rear - 1, rear)
    _box(scene, _oriented_box(side, begin, begin + width, y0, y0 + 6, front, rear),
         'minecraft:air', 'frame:dormer-hollow')
    for box in cheeks + [back, _oriented_box(side, begin, begin + width, y0, y0 + 1, front, rear),
                          _oriented_box(side, begin, begin + width, y0, y0 + 6, front, front + 1)]:
        _box(scene, box, STONE, 'frame:dormer-house')
    caps = []
    for rise, inset in ((0, 0), (1, 1), (2, 2)):
        lo, hi = begin - 1 + inset, begin + width + 1 - inset
        if lo < hi:
            box = _oriented_box(side, lo, hi, y0 + 6 + rise, y0 + 7 + rise,
                                front - 1, rear)
            _box(scene, box, ROOF, 'frame:dormer-cap')
            caps.append(box)
    return {'wing': side, 'bay_index': bay_index, 'grade': grade,
            'front_plane': front, 'window_plane': front + 2, 'reveal_depth': 2,
            'cheek_bboxes_xyz_half_open': cheeks, 'back_bbox_xyz_half_open': back,
            'roof_cap_bboxes_xyz_half_open': caps,
            'shell_bbox_xyz_half_open': _oriented_box(side, begin - 1, begin + width + 1,
                                                      y0, y0 + 9, front - 1, rear),
            'slope_contact_bbox_xyz_half_open': _oriented_box(side, begin, begin + width,
                                                              y0, y0 + 6, rear - 1, rear)}


def _party_faces(width, depth, origin, segments):
    back = kit.WING_DEPTH - 1 + origin
    front_n = 5 - segments['north'][-1]['projection'] + origin
    front_w = 5 - segments['west'][-1]['projection'] + origin
    rows = [
        ('north-east-end', 'x', width - 1, [width - 1, 0, front_n, width, 29, back + 1]),
        ('north-south-party', 'z', back, [back + 1, 0, back, width, 46, back + 1]),
        ('west-east-party', 'x', back, [back, 0, back + 1, back + 1, 46, depth]),
        ('west-south-end', 'z', depth - 1, [front_w, 0, depth - 1, back + 1, 29, depth]),
    ]
    return [{'face': face, 'axis': axis, 'coordinate': coordinate,
             'bbox_xyz_half_open': bbox, 'surface_bbox_xyz_half_open': bbox,
             'glazing_allowed': False,
             'roof_continuation': 'measured_slope' if 'end' in face else 'ridge'}
            for face, axis, coordinate, bbox in rows]


def build_frame(plan, composition, work_dir=None, *, persist=True):
    """Build (scene, manifest) for atlas tiers 0/1 using a validated composition.

    The complete fixed source level order is a geometric control, independent of
    HousePlan.storeys. All width/depth and output-path checks happen before any
    artifact is written. ``work_dir`` must be inside the project tree.
    """
    validate_composition(composition)
    if plan.form != 'corner_house':
        raise ValueError('atlas bare frame requires corner_house')
    if composition['plan'] != {key: getattr(plan, key)
                                for key in ('form', 'width', 'depth', 'seed')}:
        raise ValueError('atlas frame composition does not match the requested plan')
    if work_dir is None and persist:
        raise ValueError('atlas bare frame requires a project-local work_dir')
    output_dir = Path(work_dir).resolve() if work_dir is not None else None
    if output_dir is not None:
        output_dir.relative_to(ROOT.resolve())
    origin = composition['corner']['origin_margin']
    projection = composition['corner']['projection']
    phase, rhythm = composition['rhythm']['phase'], composition['rhythm']['pattern']
    xs = _positions(composition['wings']['north'], kit.BAY_START_NORTH, phase, rhythm)
    zs = _positions(composition['wings']['west'], kit.BAY_START_WEST, phase, rhythm)
    spans = {'north': xs[-1] + 6, 'west': zs[-1] + 6}
    width, depth = spans['north'] + origin, spans['west'] + origin
    if width > plan.width or depth > plan.depth:
        raise ValueError('atlas bare frame exceeds the requested width/depth budget')
    segments = {
        'north': _segments(composition['wings']['north'], xs, spans['north'], 0),
        'west': _segments(composition['wings']['west'], zs, spans['west'], kit.BAY_START_WEST),
    }
    scene = Scene(width, 52, depth)
    geometric_segments, balconies, openings, roof_accessories = [], [], [], []
    source_openings = []
    relief = {'schema_version': 1, 'base_projection': 1, 'pavilion_projection': 2,
              'window_reveal_depth': 2, 'base_courses': [], 'plinth_courses': [],
              'cornice_courses': [], 'dormer_houses': [], 'corner_courses': []}
    for side in ('north', 'west'):
        for segment in segments[side]:
            p = segment['projection']
            lo, hi = segment['lo'] + origin, segment['hi'] + origin
            front, roof_front = 5 - p + origin, 3 - p + origin
            bbox = _oriented_box(side, lo, hi, 0, 29, front, kit.WING_DEPTH + origin)
            _box(scene, bbox, STONE, 'frame:wing-body')
            base_bbox = _oriented_box(side, lo, hi, 0, 6, front - 1, front)
            _box(scene, base_bbox, STONE, 'frame:base-projection')
            plinth_bbox = _oriented_box(side, lo, hi, 0, 1, front - 1, kit.WING_DEPTH + origin)
            _box(scene, plinth_bbox,
                 PLINTH, 'frame:plinth')
            for key, box in (('base_courses', base_bbox), ('plinth_courses', plinth_bbox)):
                relief[key].append({'wing': side, 'group': segment['group'],
                                    'wall_front': front, 'projection': 1,
                                    'bbox_xyz_half_open': box})
            # The fine source kit has frozen corner joints under its source
            # cap. In a full-block abstraction, extruding the north strip from
            # axis zero would obscure that cap with a large rectangular mass.
            # The plain corner cap owns this near-corner zone instead.
            roof_lo = max(segment['roof_lo'] + origin, 11 + origin)
            for local, top in enumerate(ROOF_TOPS):
                if top is None:
                    continue
                inward = roof_front + local
                # Outward pavilions shift the same profile. The rear common
                # wall stays fixed; continue its missing last ridge course.
                if inward >= kit.WING_DEPTH + origin:
                    continue
                roof_bbox = _oriented_box(side, roof_lo, hi, 29, 30 + top, inward, inward + 1)
                _box(scene, roof_bbox, ROOF, 'frame:wing-roof')
            rear = kit.WING_DEPTH - 1 + origin
            _box(scene, _oriented_box(side, roof_lo, hi, 29, 46, rear, rear + 1),
                 ROOF, 'frame:roof-ridge-closure')
            for y, role in ((12, 'lower'), (27, 'upper')):
                balcony_bbox = _oriented_box(side, lo, hi, y, y + 1, front - 1, front + 1)
                _box(scene, balcony_bbox, STONE, 'frame:balcony-baseline')
                balconies.append({'wing': side, 'group': segment['group'], 'role': role,
                                  'y': y, 'projection': 1, 'pavilion_projection': p,
                                  'wall_front': front, 'bbox_xyz_half_open': balcony_bbox})
            for y, distance in ((26, 0), (27, 1), (28, 2)):
                course = _oriented_box(side, lo, hi, y, y + 1, front - distance, front + 1)
                _box(scene, course, STONE, 'frame:cornice-course')
                relief['cornice_courses'].append({'wing': side, 'group': segment['group'],
                                                 'wall_front': front, 'y': y,
                                                 'projection': distance, 'bbox_xyz_half_open': course})
            geometric_segments.append({
                'wing': side, 'group': segment['group'], 'role': segment['role'],
                'projection': p, 'axis_interval': [lo, hi], 'wall_front': front,
                'roof_front': roof_front, 'body_bbox_xyz_half_open': bbox,
                'roof_bbox_xyz_half_open': _oriented_box(side, roof_lo, hi, 29, 46,
                                                        roof_front + 3, kit.WING_DEPTH + origin),
            })
    delta, relief['corner_courses'] = _corner_body(scene, origin, projection)
    roof_accessories.append({
        'role': 'corner_cap', 'wing': None, 'bay_index': None,
        'bbox_xyz_half_open': [1 + delta, 29, 1 + delta, 13 + delta, 47, 16 + delta],
    })

    # All roof houses are constructed before cutting any windows: an orthogonal
    # shell can therefore never bury a window written earlier on the other wing.
    for side, positions in (('north', xs), ('west', zs)):
        for index, axis0 in enumerate(positions):
            bay = composition['wings'][side]['bays'][index]
            p, axis = bay['projection'], axis0 + origin
            front = 5 - p + origin
            if bay['dormer_grade'] != 'none':
                pavilion = bay['dormer_grade'] == 'pavilion'
                for grade, y0, dw in (('lower', 31, 4), ('upper', 36, 6 if pavilion else 4)):
                    house = _dormer_house(scene, side, axis, front, y0, dw, grade, index)
                    relief['dormer_houses'].append(house)
                    roof_accessories.append({
                        'role': grade + '_dormer', 'wing': side, 'bay_index': index,
                        'bbox_xyz_half_open': house['shell_bbox_xyz_half_open'],
                    })
    for side, positions in (('north', xs), ('west', zs)):
        for index, axis0 in enumerate(positions):
            bay = composition['wings'][side]['bays'][index]
            p, axis = bay['projection'], axis0 + origin
            front = 5 - p + origin
            if bay['dormer_grade'] != 'none':
                _opening(scene, openings, side, [axis + 1, axis + 2], list(range(33, 36)),
                         [front + 3] * 3, role='lower_dormer', bay_index=index,
                         stage_scope='bare_massing', facade_front=front + 1, reveal_depth=2)
                _opening(scene, openings, side, [axis + 1, axis + 2], list(range(38, 41)),
                         [front + 7] * 3, role='upper_dormer', bay_index=index,
                         stage_scope='bare_massing', facade_front=front + 5, reveal_depth=2)
            _opening(scene, openings, side, [axis, axis + 1, axis + 2], list(range(1, 6)),
                     [front + 1] * 5, role='shop_placeholder', bay_index=index,
                     stage_scope='bare_massing', facade_front=front - 1, reveal_depth=2)
            _opening(scene, openings, side, [axis + 1, axis + 2], list(range(7, 10)),
                     [front + 2] * 3, role='standard', bay_index=index,
                     facade_front=front, reveal_depth=2)
            _opening(scene, openings, side, [axis + 1, axis + 2], list(range(14, 18)),
                     [front + 2] * 4, role='noble_lower', bay_index=index,
                     facade_front=front, reveal_depth=2)
            _opening(scene, openings, side, [axis + 1, axis + 2], list(range(20, 23)),
                     [front + 2] * 3, role='noble_upper', bay_index=index,
                     facade_front=front, reveal_depth=2)
            for role, ys, planes in (('standard', list(range(7, 11)), [front] * 4),
                                     ('noble_lower', list(range(14, 18)), [front + 1, front, front, front]),
                                     ('noble_upper', list(range(20, 24)), [front] * 4)):
                _source_opening(source_openings, side, [axis + 1, axis + 2], ys, planes,
                                role=role, bay_index=index)
    for side, axes, front in (('north', [6 + delta, 7 + delta], 4 + delta),
                              ('west', [8 + delta, 9 + delta], 3 + delta)):
        for role, ys in (('standard', list(range(7, 11))),
                         ('noble_lower', list(range(15, 18))),
                         ('noble_upper', list(range(20, 24)))):
            _opening(scene, openings, side, axes, ys, [front] * len(ys),
                     role='corner_' + role, corner=True,
                     facade_front=front - 2, reveal_depth=2)
            _source_opening(source_openings, side, axes, ys, [front] * len(ys),
                            role='corner_' + role, corner=True)

    spec = {
        'schema_version': 1, 'stage': 'frameworks', 'street_faces': ['north', 'west'],
        'origin_xyz': [origin, 0, origin],
        'bounds_xyz_half_open': [0, 0, 0, width, 52, depth],
        'occupied_envelope_upper_xyz': [width, 47, depth],
        'fixed_levels': FIXED_LEVELS, 'wing_segments': geometric_segments,
        'roof_profile': {
            'datum_y': 29, 'depth_local_top_y': list(ROOF_TOPS),
            'source_id': 'v4:st1-roof-section', 'source_crop': [0, 0, 0, 3, 17, 20],
            'classification': 'main_slate_basalt_and_neutral_ridge_excludes_facade_ornament',
            'application': 'measured_shape_controls_only_no_source_piece_stamp',
        },
        'roof_joint_bbox_xyz_half_open': [3 + origin, 29, 11 + origin, 23 + origin, 46, 23 + origin],
        'corner': {
            'family': 'turret', 'projection': projection, 'offset_from_wings_xyz': [-projection, 0, -projection],
            'body_bbox_xyz_half_open': [delta, 0, 1 + delta, 11 + delta, 29, 12 + delta],
            'cap_bbox_xyz_half_open': [1 + delta, 29, 1 + delta, 13 + delta, 47, 16 + delta],
            'cap_top_y': 46, 'abstraction': 'quarter_rounded_body_and_plain_stepped_mansard_cap',
        },
        'openings': openings, 'source_openings': source_openings,
        'relief_geometry': relief, 'party_faces': _party_faces(width, depth, origin, segments),
        'roof_accessory_bboxes': roof_accessories,
        'balcony_baselines': balconies,
        'limitations': ['plain_shop_glazing_is_framework_only',
                        'plain_aperture_heights_3_4_3_are_abstractions_of_shared_source_levels',
                        'native_source_window_planes_are_separate_from_plain_recessed_glazing',
                        'corner_cap_height_is_a_massing_control_not_a_finial',
                        'fixed_source_layer_order_not_arbitrary_storey_count'],
    }
    not_applicable = {
        'status': 'NOT_APPLICABLE',
        'reason': 'Bare massing consumes no fine source pieces and makes no source-stamp claim.',
    }
    manifest = {
        'run': output_dir.name if output_dir is not None else None,
        'seed': plan.seed, 'plan': plan.describe(),
        'atlas_tier_semantics': 'bare_massing', 'stage': 'frameworks',
        'composition': deepcopy(composition), 'atlas_frame_spec': spec,
        'framework_geometry': deepcopy(spec),
        'scene': {'width': width, 'height': 52, 'depth': depth,
                  'bays_north': [x + origin for x in xs], 'bays_west': [z + origin for z in zs]},
        'techniques': [], 'stamps': [], 'stamp_audit': [], 'stamp_audit_rows': [],
        'stamp_audit_policy': [], 'derived_pieces': {}, 'piece_sources': [],
        'source_trace': deepcopy(not_applicable), 'atlas_audit': deepcopy(not_applicable),
        'materials': {'body': STONE, 'plinth': PLINTH, 'roof': ROOF, 'placeholder_glass': GLASS},
        'artifact_role': 'FRAMEWORK_CANDIDATE_NOT_FINAL_DELIVERABLE',
        'architectural_review': 'PENDING', 'game_acceptance': 'NOT_RUN',
    }
    if persist:
        schem_path = output_dir / 'ATLAS-FRAME.schem'
        exported = write_schematic(schem_path, scene.volume, scene.palette, name=NAME)
        read_back = load_schematic(schem_path)
        manifest.update(schematic={'path': str(schem_path.relative_to(ROOT)), **exported},
                        validation=read_back.validation(), independent_registry=validate_vanilla(schem_path))
        dump_json(output_dir / 'composition.json', composition)
        dump_json(output_dir / 'frame.json', manifest)
    return scene, manifest
