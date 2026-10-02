"""Readable export measurements and deliberately narrow plan comparisons.

This module consumes a facade_section report. It neither consults manifests nor
turns material-family observations into architectural or game acceptance.
"""
from __future__ import annotations

import json

from .schematic import AIR_BLOCKS, base_block


FACE_LABELS = {
    'street_north': 'north (-z), assumed street face',
    'street_east': 'east (+x), assumed street face',
    'chamfer': 'north-east diagonal, assumed chamfer face',
    'party_west': 'west (-x), assumed blind party face',
    'party_south': 'south (+z), assumed blind party face',
}
LEGEND = (
    '.=air G=glass #=stone R=roof-family W=planks '
    'F=door/trapdoor/bars (frame-capable material) O=other ?=unavailable'
)


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _material(palette, palette_id):
    if palette_id is None or not isinstance(palette_id, int) or not 0 <= palette_id < len(palette):
        return '?'
    name = base_block(palette[palette_id])
    if name in AIR_BLOCKS:
        return '.'
    if 'glass' in name:
        return 'G'
    if 'deepslate' in name or 'blackstone' in name:
        return 'R'
    if any(part in name for part in ('sandstone', 'stone_bricks', 'quartz')):
        return '#'
    if name.endswith('_planks'):
        return 'W'
    if name.endswith(('_door', '_trapdoor')) or name == 'minecraft:iron_bars':
        return 'F'
    return 'O'


def _rows(data, y_range=None):
    start = data.get('start_y', 1)
    rows = [(start + index, row) for index, row in enumerate(data.get('palette_ids_y_axis_depth', []))]
    if y_range is not None:
        rows = [(y, row) for y, row in rows if y_range[0] <= y <= y_range[1]]
    return list(reversed(rows))


def _ray_char(ray, depths, palette, depth):
    try:
        index = depths.index(depth)
    except ValueError:
        return '?'
    return _material(palette, ray[index]) if index < len(ray) else '?'


def _opening_char(ray, depths, palette):
    """Glass depth or a clear 4-cell ray; opaque thin blocks remain blocking."""
    for depth in range(4):
        char = _ray_char(ray, depths, palette, depth)
        if char == 'G':
            return str(depth)
        if char != '.':
            return '?' if char == '?' else '-'
    return 'P'


def _projection_char(ray, depths, palette):
    missing = False
    for depth in (-3, -2, -1):
        char = _ray_char(ray, depths, palette, depth)
        if char == '?':
            missing = True
            continue
        if char != '.':
            return str(-depth)
    return '?' if missing else '.'


def _draw(lines, title, rows, transform):
    lines.append(title)
    for y, row in rows:
        lines.append(f'y={y:03d} | ' + ''.join(transform(ray) for ray in row))


def _course_summary(report, y_range=None):
    """Keep located gaps and measured connection status without repeating voxel sets."""
    result = []
    for course in report.get('courses', []):
        y = course.get('y')
        if y_range is not None and not y_range[0]-1 <= y <= y_range[1]+1:
            continue
        faces = {}
        for face, data in course.get('faces', {}).items():
            coords = report.get('surface_maps', {}).get(face, {}).get('coordinates_xz', [])
            gaps = []
            for a, b in data.get('gaps', []):
                gaps.append({'axis_indices':[a,b], 'endpoints_xz':[coords[a],coords[b]]
                             if 0 <= a <= b < len(coords) else None})
            connection = data.get('stone_path_connection', {})
            faces[face] = {key:data.get(key) for key in ('sample_count','covered_cells','longest_run')}
            faces[face].update(gaps=gaps, stone_connected=connection.get('connected'),
                               connection_status=connection.get('status'))
        result.append({'y':y, 'sampled_path_coverage_complete':course.get('sampled_path_coverage_complete'),
                       'stone_connected':course.get('stone_path_connection', {}).get('connected'), 'faces':faces})
    return result


def text_evidence(report, storey=None, include_roof=True):
    """Return ASCII single-cell grids, coordinates, hashes and measurement limits.

    A storey filter limits facade rows and opening details. Roof slices, when
    requested, retain actual per-y material cells instead of filling height traces.
    """
    source = report.get('source', {})
    lines = [
        'EXPORT VOXEL EVIDENCE (local integer coordinates, one ASCII character per sampled cell)',
        'source=' + _json(source),
        'coordinates: north=-z; east=+x; west=-x; south=+z; y increases upward.',
        'Face role labels are the measurement convention, not independently measured street/party-wall use.',
        'status=' + str(report.get('status', 'unmeasured')),
    ]
    if report.get('reason'):
        lines.append('reason=' + report['reason'])
    lines.extend('LIMIT: ' + str(value) for value in report.get('limitations', []))
    lines.extend([
        'LIMIT: Integer occupied cells do not establish slab/stair/door model dimensions or window-frame roles.',
        'LIMIT: Inward/outward depths count ray steps; on the NE diagonal each step changes both x and z.',
        'LIMIT: These observations do not establish style, mansard compliance, visual approval or game acceptance.',
    ])
    if report.get('status') != 'measured':
        return '\n'.join(lines)
    lines.append('footprint=' + _json(report.get('footprint', {})))
    lines.append('measured floor plates y=' + _json(report.get('floors_y', [])))
    storeys = report.get('storeys', [])
    y_range = None
    if storey is not None:
        selected = next((row for row in storeys if row.get('storey') == storey), None)
        storeys = [selected] if selected else []
        y_range = selected['y_range'] if selected else []
        lines.append(f'facade scope: storey={storey}; y_range={_json(y_range)}')
        if not selected:
            lines.append('UNMEASURED: requested storey is absent; no other storey is substituted.')
    lines.append('material legend: ' + LEGEND)
    palette = report.get('palette', [])
    for face, data in report.get('surface_maps', {}).items():
        lines.append('\nFACE ' + face + ' | ' + FACE_LABELS.get(face, 'unclassified face'))
        coords = data.get('coordinates_xz', [])
        if coords:
            xs, zs = zip(*coords)
            if len(set(zs)) == 1:
                lines.append(f'grid axes: horizontal x={xs[0]}..{xs[-1]}; fixed z={zs[0]}; vertical y')
            elif len(set(xs)) == 1:
                lines.append(f'grid axes: horizontal z={zs[0]}..{zs[-1]}; fixed x={xs[0]}; vertical y')
            else:
                lines.append('grid axes: horizontal sample i with coupled x,z below; vertical y (NE diagonal, not a straight x/z plane)')
        lines.append('columns i:x,z = ' + ' '.join(f'{i}:{x},{z}' for i, (x, z) in enumerate(coords)))
        lines.append('column i%10  | ' + ''.join(str(i % 10) for i in range(len(coords))))
        lines.append('inward_step_xz=' + _json(data.get('inward_step_xz')))
        rows = [] if y_range == [] else _rows(data, y_range)
        if not rows:
            lines.append('UNMEASURED: no material grid rows in the requested scope.')
            continue
        depths = data.get('depths', [])
        _draw(lines, 'skin material at d=0:', rows,
              lambda ray: _ray_char(ray, depths, palette, 0))
        _draw(lines, 'inward ray: 0..3=glass depth, P=4 air cells (sampled portal), -=blocked, ?=unknown:', rows,
              lambda ray: _opening_char(ray, depths, palette))
        _draw(lines, 'outward occupancy: 1..3=outermost observed occupied ray step, .=all three air, ?=unknown:', rows,
              lambda ray: _projection_char(ray, depths, palette))
    for row in storeys:
        lines.append(f'\nOPENING GROUPS storey={row.get("storey")} y={_json(row.get("y_range"))}')
        for face, data in row.get('faces', {}).items():
            groups = data.get('openings', [])
            lines.append(f'{face}: sampled groups={len(groups)}; groups are not a semantic window count.')
            for index, opening in enumerate(groups):
                lines.append(f'  group {index}: xz={_json(opening.get("endpoints_xz"))} '
                             f'y={_json(opening.get("y_range"))} '
                             f'width_cells={opening.get("width_cells")} height_cells={opening.get("height_cells")} '
                             f'inward_ray_step_counts={_json(opening.get("depth_counts", {}))} '
                             f'kinds={_json(opening.get("kinds", []))}')
    courses = [] if y_range == [] else _course_summary(report, y_range)
    if courses:
        lines.append('\nMASONRY PATH OBSERVATIONS: coverage/connectivity only; architectural roles are unmeasured.')
        lines.extend(_json(course) for course in courses)
    if include_roof:
        lines.append('\nROOF VOXEL SLICES: actual material cells; air remains air.')
        slices = report.get('roof_slices', [])
        if not slices:
            lines.append('UNMEASURED: no per-y voxel slices; top-height traces cannot establish interior occupancy or a mansard.')
        for section in slices:
            axis = section.get('axis')
            fixed_axis = 'z' if axis == 'x' else 'x'
            start, end = section.get('start', 0), section.get('end', -1)
            direction = 'west -> east' if axis == 'x' else 'north -> south'
            lines.append(f'{axis} slice @{fixed_axis}={section.get("fixed_coordinate")}; '
                         f'{axis}={start}..{end} ({direction}); y increases upward')
            lines.append('legend=' + _json(section.get('legend', {})))
            lines.append('column i%10  | ' + ''.join(str(i % 10) for i in range(max(0, end-start+1))))
            for row in section.get('rows', []):
                lines.append(f'y={row["y"]:03d} | {row["cells"]}')
        lines.append('Roof-family cells may include dormers, chimneys and cresting; no ridge, slope break or run/rise is inferred.')
    return '\n'.join(lines)


def compare_plan(plan, report):
    """Compare only explicit, supported scalar expectations and sampled openings.

    Unsupported entries are retained as unresolved scopes. In particular bay_pitch
    supplies no window schedule, and masonry coverage supplies no cornice role.
    There is deliberately no overall building pass or game-acceptance result.
    """
    if hasattr(plan, 'describe'):
        plan = plan.describe()
    plan = plan or {}
    footprint = report.get('footprint', {})
    measured = report.get('status') == 'measured'
    form = plan.get('form')
    geometry = report.get('supported_geometry', {})
    supported = (measured and form == 'corner_house'
                 and geometry.get('supports_ne_corner_sampling') is True
                 and footprint.get('supported_pattern') is True)
    checks = []

    def add(name, expected, actual, coordinates, *, reason='', allowed=supported, scope='measured'):
        explicit = expected is not None
        status = ('pass' if actual == expected else 'fail') if allowed and explicit and actual is not None else 'unsupported'
        checks.append({'id': name, 'expected': expected, 'actual': actual, 'status': status,
                       'scope': scope if explicit else 'unscoped', 'coordinates': coordinates,
                       'limitation': reason})

    add('form_orientation', form, {'foundation_bounds_xz': footprint.get('bounds_xz'),
                                 'north_east_cut_cells': footprint.get('north_east_cut_cells'),
                                 'diagonal_xz': footprint.get('diagonal_xz')},
        {'bounds_xz': footprint.get('bounds_xz'), 'diagonal_xz': footprint.get('diagonal_xz')},
        allowed=False, scope='unmeasured',
        reason='The sampler assumes a NE corner with north/east street and west/south party faces. '
               'Material/footprint measurements cannot independently prove architectural use or orientation; other forms are unsupported.')
    for name in ('width', 'depth'):
        add(name, plan.get(name), footprint.get(name), {'bounds_xz': footprint.get('bounds_xz')},
            reason='Foundation bounding extent, not facade projection extent. Supported comparison requires a validated rectangular/NE-cut foundation and the NE corner sampler.')
    floors = report.get('floors_y', [])
    add('storeys', plan.get('storeys'), len(floors)-1 if len(floors) >= 2 else None,
        {'floors_y': floors, 'intervals_y': [row.get('y_range') for row in report.get('storeys', [])]},
        reason='Counts intervals between broad wooden floor plates; unsupported floor materials, mezzanines and duplicate plates may escape this proxy.')
    add('chamfer', plan.get('chamfer'), footprint.get('north_east_cut_cells'),
        {'bounds_xz': footprint.get('bounds_xz'), 'diagonal_xz': footprint.get('diagonal_xz')},
        reason='Missing foundation cells along the north edge of the NE cut; no default value is inferred when plan.chamfer is absent.')
    for face in ('party_west', 'party_south'):
        rows = report.get('storeys', [])
        entries = [row.get('faces', {}).get(face) for row in rows]
        count = sum(entry.get('sampled_transmissive_groups_count', entry.get('opening_count', 0))
                    for entry in entries if entry is not None) if entries and all(entry is not None for entry in entries) else None
        groups = [{'storey': row.get('storey'), 'y_range': row.get('y_range'),
                   'openings': row.get('faces', {}).get(face, {}).get('openings', [])} for row in rows]
        add(face + '.sampled_transmissive_groups', 0 if form == 'corner_house' else None, count,
            {'surface_coordinates_xz': report.get('surface_maps', {}).get(face, {}).get('coordinates_xz'), 'groups': groups},
            scope='sampled', reason='Zero air/glass ray groups on the sampled skin and storey rows only; '
                                  'does not prove all wall voxels opaque or thin block models watertight.')
    observed_groups = [{'storey':row.get('storey'), 'faces':{
        face:data.get('sampled_transmissive_groups_count', data.get('opening_count'))
        for face,data in row.get('faces', {}).items()}} for row in report.get('storeys', [])]
    group_coordinates = [{'storey':row.get('storey'), 'y_range':row.get('y_range'), 'faces':{
        face:[{key:opening.get(key) for key in ('axis_indices','endpoints_xz','y_range')}
              for opening in data.get('openings', [])]
        for face,data in row.get('faces', {}).items()}} for row in report.get('storeys', [])]
    add('window_schedule', plan.get('window_schedule'), observed_groups, {'storeys': group_coordinates},
        allowed=False, scope='unmeasured', reason='No supported per-window expectation or semantic window identification; '
                                                'bay_pitch is not converted into an expected count.')
    roof_expected = {key: plan[key] for key in ('roof_height', 'roof_profile', 'roof_run', 'roof_rise') if key in plan}
    add('roof_profile', roof_expected or None, report.get('roof_section'),
        {'slices': [{key: section.get(key) for key in ('axis', 'fixed_coordinate', 'start', 'end', 'start_y', 'end_y')}
                    for section in report.get('roof_slices', [])]},
        allowed=False, scope='unmeasured', reason='No supported expected run/rise or slope-break schedule. '
                                                'Roof-family maxima include spikes and cannot establish mansard compliance.')
    add('course_roles', plan.get('course_schedule'), _course_summary(report),
        {'sampled_faces': {face: data.get('coordinates_xz') for face, data in report.get('surface_maps', {}).items()}},
        allowed=False, scope='unmeasured', reason='Stone coverage/connectivity is measured geometry; '
                                                'cornice, string-course and balcony role expectations are unscoped.')
    return {'version': 1, 'source': dict(report.get('source', {})), 'measurement_status': report.get('status', 'unmeasured'),
            'checks': checks, 'limitations': list(report.get('limitations', [])) + [
                'pass/fail applies only to the named sampled or proxy check, never to an entire architectural requirement.',
                'Unsupported/unscoped checks remain unresolved; images, model review and user-only game acceptance still apply.',
                'No manifest geometry, inferred window count, roof-form verdict or overall acceptance is used.']}


def review_description(plan, report, storey=None, include_roof=True):
    """Return a JSON-serializable model payload with readable grids and exact diff."""
    return {'source': dict(report.get('source', {})),
            'text': text_evidence(report, storey=storey, include_roof=include_roof),
            'comparison': compare_plan(plan, report)}
