"""Scoped architectural predicates measured from exported blocks.

The default NE-corner adapter proves footprint dimensions, plate intervals,
opaque party skins and visible recessed glazing. It does not rename those
predicates as complete architectural layers. Additional placement, alignment,
band and contact obligations need an explicit ``plan['conformance_spec']``.
Unsupported explicit obligations stay pending instead of being guessed.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

import numpy as np

from . import facade_section
from .schematic import AIR_BLOCKS, base_block, load_schematic


REPORT_VERSION = 1
POLICY_ID = 'export-ne-corner-v1'
SPEC_KEYS = {'orientation', 'floors_y', 'openings', 'aligned_storeys', 'courses', 'contacts'}
STREET_FACES = ('street_north', 'street_east', 'chamfer')
PARTY_FACES = ('party_west', 'party_south')
LIMITATIONS = [
    'Only the fixed north/east-street, west/south-party corner adapter is supported; use roles are a declared policy, not inferred from materials.',
    'Floor counts and heights use independently measured broad wooden plate bands; other floor materials are unsupported.',
    'Glazing recession is an integer inward ray step, not a sub-block model dimension; diagonal steps change both x and z.',
    'Sampled transmissive components are not semantic windows. Bay pitch is never converted to a window schedule.',
    'Masonry connectivity proves face-adjacent classified cells; stairs/slabs/panes may occupy only part of each cell.',
    'Window-frame roles, sill/lintel model contact and architectural course roles need explicit supported specifications.',
    'This report establishes only its named predicates. Visual quality and user-only game acceptance are separate.',
]


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def _plan(plan):
    value = plan.describe() if hasattr(plan, 'describe') else dict(plan or {})
    return {k: v for k, v in value.items() if k != '_stage'}


def plan_hash(plan):
    return sha256(_canonical(_plan(plan)).encode('utf-8')).hexdigest()


def validator_digest():
    """Bind the algorithms this receipt depends on, including roof extraction."""
    digest = sha256()
    for name in ('architectural_conformance.py', 'facade_section.py', 'roof_conformance.py', 'atlas_conformance.py'):
        digest.update(name.encode('ascii'))
        digest.update(Path(__file__).with_name(name).read_bytes())
    atlas_measurements = Path(__file__).resolve().parents[2] / 'tools' / 'verify_atlas_composition.py'
    digest.update(b'tools/verify_atlas_composition.py')
    digest.update(atlas_measurements.read_bytes())
    return digest.hexdigest()


def _solid_cube(name):
    # Deliberately restricted to blocks whose ordinary full-cube model is known.
    return (name.endswith('_planks') or name in {
        'minecraft:sandstone', 'minecraft:smooth_sandstone', 'minecraft:cut_sandstone',
        'minecraft:chiseled_sandstone', 'minecraft:stone_bricks', 'minecraft:mossy_stone_bricks',
        'minecraft:cracked_stone_bricks', 'minecraft:chiseled_stone_bricks',
        'minecraft:quartz_block', 'minecraft:smooth_quartz', 'minecraft:quartz_bricks',
        'minecraft:quartz_pillar', 'minecraft:stone', 'minecraft:glass',
    } or name.endswith('_stained_glass'))


def _integer_pair(value):
    return isinstance(value, (list, tuple)) and len(value) == 2 and all(type(v) is int for v in value) and value[0] <= value[1]


def _points_connected(points):
    remaining = set(points)
    if not remaining:
        return False
    todo = [remaining.pop()]
    while todo:
        x, y, z = todo.pop()
        for q in ((x-1,y,z), (x+1,y,z), (x,y-1,z), (x,y+1,z), (x,y,z-1), (x,y,z+1)):
            if q in remaining:
                remaining.remove(q)
                todo.append(q)
    return not remaining


def _summary(checks):
    counts = Counter(check['status'] for check in checks)
    required = Counter(check['status'] for check in checks if check.get('required'))
    return {'pass': counts['pass'], 'fail': counts['fail'], 'unsupported': counts['unsupported'],
            'required_fail': required['fail'], 'required_unsupported': required['unsupported']}


def _status(summary):
    return 'FAIL' if summary['required_fail'] else 'UNSUPPORTED' if summary['required_unsupported'] else 'PASS'


def failures(report):
    return [check for check in report.get('checks', []) if check.get('required') and check.get('status') == 'fail']


def pending(report):
    return [check for check in report.get('checks', []) if check.get('required') and check.get('status') == 'unsupported']


def measure(schematic, plan=None, section=None, *, stage=None):
    """Return independent checks bound to the export, plan, policy and stage.

    ``conformance_spec.openings`` entries name a face, storey, axis_indices and
    y_range of one sampled transmissive component. Optional depth_range_steps
    checks its ray depths; ``glazing_connected=True`` checks actual full-cube
    glazing cells, not frame contact. ``aligned_storeys`` entries name face and
    storeys; exact observed component centre sets are compared. ``courses``
    name y and faces; only known measured masonry strips are supported.
    ``contacts`` explicitly name two adjacent xyz cells and their exact states;
    only known full-cube model contact is supported. No inferred role schedule
    or generator/manifest coordinates are used as measured observations.
    """
    if _plan(plan).get('detail_profile') == 'atlas_street1':
        from .atlas_conformance import measure as measure_atlas
        return measure_atlas(schematic, plan, section, stage=stage)
    path = Path(schematic)
    raw_plan = plan or {}
    stage = stage or (raw_plan.get('_stage') if isinstance(raw_plan, dict) else None) or 'facades'
    plan = _plan(raw_plan)
    s = load_schematic(path)
    source = {'path': str(path.resolve()), 'sha256': sha256(path.read_bytes()).hexdigest(),
              'voxel_state_hash': s.voxel_state_hash()}
    if section is None:
        section = facade_section.measure(path)
    if (section.get('version') != facade_section.REPORT_VERSION
            or any(section.get('source', {}).get(key) != source[key] for key in ('sha256', 'voxel_state_hash'))):
        raise ValueError('Section evidence is stale or belongs to another export')
    footprint = section.get('footprint', {})
    floors = section.get('floors_y', [])
    spec = plan.get('conformance_spec', {})
    checks = []

    def add(ident, status, observation, *, expected=None, actual=None, coordinates=None, required=True, scope='voxel'):
        checks.append({'id': ident, 'status': status, 'required': required, 'observation': observation,
                       'reason': observation, 'expected': expected, 'actual': actual,
                       'coordinates': coordinates or {}, 'scope': scope})

    if not isinstance(spec, dict):
        add('spec/schema', 'unsupported', 'conformance_spec must be an object; the explicit obligations cannot be interpreted.')
        spec = {}
    for key in sorted(set(spec) - SPEC_KEYS):
        add('spec/' + key, 'unsupported', 'No implemented predicate for explicitly requested specification key: ' + key,
            expected=spec[key], scope='unmeasured')
    orientation = spec.get('orientation', 'north_east_corner')
    supported = (section.get('status') == 'measured' and plan.get('form') == 'corner_house'
                 and footprint.get('supported_pattern') is True and orientation == 'north_east_corner')
    if orientation != 'north_east_corner':
        add('topology/orientation', 'unsupported', 'The declared orientation is not supported by the north-east export sampler.',
            expected=orientation, scope='unmeasured')
    if section.get('status') != 'measured' or plan.get('form') != 'corner_house':
        add('measurement/supported_geometry', 'unsupported', section.get('reason') or
            'No supported corner-house adapter; architectural form and face obligations are not guessed.',
            expected=plan.get('form'), actual=section.get('status'), scope='unmeasured')
    for dimension in ('width', 'depth'):
        expected, actual = plan.get(dimension), footprint.get(dimension)
        allowed = section.get('status') == 'measured' and footprint.get('supported_pattern') is True
        result = ('pass' if actual == expected else 'fail') if allowed and type(expected) is int else 'unsupported'
        add('footprint/' + dimension, result,
            f'Foundation {dimension}: measured {actual}, requested {expected}.' if allowed else
            'Foundation extent comparison is unsupported for this export or missing scalar specification.',
            expected=expected, actual=actual, coordinates={'bounds_xz': footprint.get('bounds_xz')},
            required=expected is not None, scope='foundation_extent')
    expected_storeys = plan.get('storeys')
    actual_storeys = len(floors)-1 if len(floors) >= 2 else None
    add('floors/storeys', ('pass' if actual_storeys == expected_storeys else 'fail')
        if actual_storeys is not None and type(expected_storeys) is int else 'unsupported',
        f'Broad wooden plate intervals: measured {actual_storeys}, requested {expected_storeys}; plates y={floors}.',
        expected=expected_storeys, actual=actual_storeys, coordinates={'floors_y': floors},
        required=expected_storeys is not None, scope='floor_plate_proxy')
    if 'floors_y' in spec:
        expectation = spec['floors_y']
        allowed = isinstance(expectation, list) and all(type(y) is int for y in expectation) and bool(floors)
        add('floors/heights', ('pass' if floors == expectation else 'fail') if allowed else 'unsupported',
            f'Measured plate top heights {floors}; explicit schedule {expectation}.',
            expected=expectation, actual=floors, coordinates={'floors_y': floors}, scope='floor_plate_proxy')
    cut = footprint.get('north_east_cut_cells')
    expected_cut = plan.get('chamfer')
    if expected_cut is not None:
        known = section.get('status') == 'measured' and orientation == 'north_east_corner' and type(expected_cut) is int
        result = ('pass' if cut == expected_cut and footprint.get('supported_pattern') is True else 'fail') if known else 'unsupported'
        add('corner/chamfer_geometry', result,
            f'Foundation NE cut measures {cut} cells; requested {expected_cut}; supported footprint={footprint.get("supported_pattern")}. '
            'This check has no roof dependency.', expected=expected_cut, actual=cut,
            coordinates={'bounds_xz': footprint.get('bounds_xz'), 'diagonal_xz': footprint.get('diagonal_xz')}, scope='foundation_cut')

    def state_at(q):
        x, y, z = q
        return s.id_to_state[int(s.volume[y,z,x])] if 0 <= x < s.width and 0 <= y < s.height and 0 <= z < s.length else None

    # Check the entire sampled party skin, including plate rows, not merely an
    # opening-group count. Unknown block models remain explicit pending items.
    for face in PARTY_FACES:
        cells = section.get('surface_maps', {}).get(face, {}).get('coordinates_xz', [])
        coordinates = [(x,y,z) for x,z in cells for y in range(1, floors[-1]+1)] if floors else []
        bad, unknown = [], []
        for q in coordinates:
            value = state_at(q)
            name = base_block(value) if value else None
            if name in AIR_BLOCKS or (name and 'glass' in name):
                bad.append(list(q))
            elif name is None or not _solid_cube(name):
                unknown.append({'coordinate': list(q), 'state': value})
        status = 'unsupported' if not supported or not coordinates else 'fail' if bad else 'unsupported' if unknown else 'pass'
        add('topology/' + face + '_opaque', status,
            f'{face} sampled full-height skin: {len(coordinates)} cells, {len(bad)} air/glass violations, '
            f'{len(unknown)} unsupported block models; no roof checks are reused.', expected='opaque full-cube body skin',
            actual={'sampled_cells': len(coordinates), 'violations': len(bad), 'unknown_models': len(unknown)},
            coordinates={'violations_xyz': bad, 'unsupported_cells': unknown}, required=plan.get('form') == 'corner_house')

    # Built-in contract for this adapter: each street body storey exposes real
    # glazing behind the skin. It does not establish an exact bay/window count.
    for row in section.get('storeys', []):
        for face in STREET_FACES:
            if face == 'chamfer' and not cut:
                continue
            groups = [group for group in row.get('faces', {}).get(face, {}).get('openings', []) if 'glazing' in group.get('kinds', [])]
            depths = sorted({int(depth) for group in groups for depth in group.get('depth_counts', {}) if int(depth) < 4})
            ident = f'openings/{face}/storey-{row["storey"]}'
            add(ident + '/visible_glazing', 'unsupported' if not supported else 'pass' if groups else 'fail',
                f'{face} storey {row["storey"]}: {len(groups)} visible transmissive groups containing glazing; '
                'this is not a semantic window count.', expected='at least one visible glazing group', actual=len(groups),
                coordinates={'storey_y': row.get('y_range'), 'groups': [{k:g.get(k) for k in ('axis_indices','y_range','endpoints_xz')} for g in groups]},
                required=plan.get('form') == 'corner_house', scope='sampled_glazing')
            add(ident + '/recessed_glazing', 'unsupported' if not supported or not groups else 'pass' if depths and min(depths) >= 1 else 'fail',
                f'{face} storey {row["storey"]}: observed glazing inward ray steps {depths}; required minimum is one cell step.',
                expected={'minimum_inward_ray_steps': 1}, actual={'observed_steps': depths},
                coordinates={'storey_y': row.get('y_range')}, required=bool(groups) and plan.get('form') == 'corner_house', scope='sampled_glazing_depth')

    for index, opening in enumerate(spec.get('openings', [])) if isinstance(spec.get('openings', []), list) else [(0, None)]:
        ident = 'spec/opening/' + str(opening.get('id', index) if isinstance(opening, dict) else index)
        if not isinstance(opening, dict) or not {'face','storey','axis_indices','y_range'} <= set(opening):
            add(ident, 'unsupported', 'Opening placement requires face, storey, axis_indices and y_range.', expected=opening)
            continue
        allowed_keys = {'id','face','storey','axis_indices','y_range','depth_range_steps','glazing_connected'}
        if set(opening)-allowed_keys or not _integer_pair(opening['axis_indices']) or not _integer_pair(opening['y_range']):
            add(ident, 'unsupported', 'Opening declaration has unsupported fields or invalid integer ranges.', expected=opening)
            continue
        row = next((r for r in section.get('storeys', []) if r.get('storey') == opening['storey']), None)
        face = opening['face']
        observed = row.get('faces', {}).get(face, {}).get('openings', []) if row else []
        matching = [g for g in observed if g.get('axis_indices') == opening['axis_indices'] and g.get('y_range') == opening['y_range'] and 'glazing' in g.get('kinds', [])]
        allowed = supported and face in section.get('surface_maps', {}) and type(opening['storey']) is int
        add(ident + '/position', 'unsupported' if not allowed else 'pass' if len(matching) == 1 else 'fail',
            f'Explicit sampled glazing bounds {opening["axis_indices"]}, y={opening["y_range"]}: '
            f'{len(matching)} exact observed groups on {face} storey {opening["storey"]}.', expected=opening,
            actual=[{k:g.get(k) for k in ('axis_indices','y_range','depth_counts')} for g in observed],
            coordinates={'face': face, 'storey': opening['storey']}, scope='sampled_component_position')
        group = matching[0] if len(matching) == 1 else None
        if 'depth_range_steps' in opening:
            bound = opening['depth_range_steps']
            depths = sorted(int(d) for d in (group or {}).get('depth_counts', {}))
            known = allowed and _integer_pair(bound) and bound[0] >= 0 and bound[1] <= 3
            good = bool(group) and bool(depths) and all(bound[0] <= d <= bound[1] for d in depths)
            add(ident + '/depth', 'unsupported' if not known else 'pass' if good else 'fail',
                f'Explicit glazing depth range {bound}; observed ray steps {depths}; missing placement also fails this obligation.',
                expected=bound, actual=depths, coordinates={'face':face, 'storey':opening['storey']}, scope='sampled_glazing_depth')
        if 'glazing_connected' in opening:
            points, partial = [], []
            inward = section.get('surface_maps', {}).get(face, {}).get('inward_step_xz')
            if group and inward:
                for x,y,z in group.get('sample_coordinates_xyz', []):
                    for depth in range(4):
                        q = (x+depth*inward[0],y,z+depth*inward[1])
                        value = state_at(q)
                        name = base_block(value) if value else None
                        if name and 'glass' in name:
                            points.append(q)
                            if not _solid_cube(name): partial.append(list(q))
                            break
                        if name not in AIR_BLOCKS: break
            known = allowed and type(opening['glazing_connected']) is bool and not partial
            actual = _points_connected(points)
            add(ident + '/glazing_connectivity', 'unsupported' if not known else 'pass' if bool(group) and actual == opening['glazing_connected'] else 'fail',
                f'Actual glazing has {len(points)} cells; face-adjacent full-cube connectivity={actual}; '
                f'unsupported partial models={len(partial)}. This is not window-frame/sill contact.',
                expected=opening['glazing_connected'], actual=actual, coordinates={'glazing_xyz':[list(q) for q in points], 'partial_model_xyz':partial}, scope='full_cube_glazing_connectivity')

    for index, alignment in enumerate(spec.get('aligned_storeys', [])) if isinstance(spec.get('aligned_storeys', []), list) else [(0, None)]:
        ident = 'spec/alignment/' + str(index)
        known = isinstance(alignment, dict) and set(alignment) <= {'face','storeys'} and isinstance(alignment.get('storeys'), list) and len(alignment['storeys']) >= 2
        values = []
        if known:
            for storey in alignment['storeys']:
                row = next((r for r in section.get('storeys', []) if r['storey'] == storey), None)
                data = row.get('faces', {}).get(alignment.get('face')) if row else None
                values.append({'storey':storey, 'centres_xz': sorted(g['centre_xz'] for g in data.get('openings', []) if 'glazing' in g.get('kinds', [])) if data else None})
        known = known and supported and all(v['centres_xz'] is not None for v in values)
        good = known and bool(values[0]['centres_xz']) and all(v['centres_xz'] == values[0]['centres_xz'] for v in values)
        add(ident, 'unsupported' if not known else 'pass' if good else 'fail',
            f'Explicit storey alignment compares measured transmissive group centres: {values}; no bay grid is inferred.',
            expected=alignment, actual=values, scope='sampled_glazing_centres')

    for index, course in enumerate(spec.get('courses', [])) if isinstance(spec.get('courses', []), list) else [(0, None)]:
        ident = 'spec/course/' + str(course.get('id', index) if isinstance(course, dict) else index)
        known = isinstance(course, dict) and set(course) <= {'id','y','faces'} and type(course.get('y')) is int and isinstance(course.get('faces'), list) and bool(course['faces']) and set(course['faces']) <= set(STREET_FACES)
        observed = next((c for c in section.get('courses', []) if c['y'] == course['y']), None) if known else None
        known = known and supported
        selected = course['faces'] if known else []
        face_data = {f:(observed or {}).get('faces', {}).get(f) for f in selected}
        full_path = set(selected) == set(STREET_FACES)
        # The sampler has a real union path only for all three adjacent faces.
        # It cannot prove turning connectivity for an arbitrary two-face subset.
        if 1 < len(selected) < 3:
            known = False
        good = bool(observed) and all(d and not d.get('gaps') and d.get('stone_path_connection', {}).get('connected') is True for d in face_data.values())
        if full_path:
            good = good and observed.get('stone_path_connection', {}).get('connected') is True
        add(ident, 'unsupported' if not known else 'pass' if good else 'fail',
            f'Explicit masonry course y={(course or {}).get("y") if isinstance(course,dict) else None}: '
            f'projected coverage and a single face-adjacent stone path must both hold on {selected}; connected={bool(good)}. '
            'This does not prove contact between partial slab/stair models.', expected=course,
            actual={f:{'gaps':d.get('gaps'), 'connected':d.get('stone_path_connection',{}).get('connected')} if d else None for f,d in face_data.items()},
            coordinates={'y':(course or {}).get('y') if isinstance(course,dict) else None}, scope='masonry_voxel_path')

    for index, contact in enumerate(spec.get('contacts', [])) if isinstance(spec.get('contacts', []), list) else [(0, None)]:
        ident = 'spec/contact/' + str(contact.get('id', index) if isinstance(contact,dict) else index)
        known = isinstance(contact,dict) and set(contact) <= {'id','a_xyz','b_xyz','a_state','b_state'} and {'a_xyz','b_xyz','a_state','b_state'} <= set(contact)
        coords = [contact.get(k) for k in ('a_xyz','b_xyz')] if known else []
        known = known and all(isinstance(q,list) and len(q)==3 and all(type(v) is int for v in q) for q in coords)
        actual = [state_at(q) for q in coords] if known else []
        adjacent = known and sum(abs(a-b) for a,b in zip(*coords)) == 1
        expectations = [contact.get(k) for k in ('a_state','b_state')] if isinstance(contact,dict) else []
        models_known = known and all(isinstance(value,str) and _solid_cube(base_block(value)) and base_block(value) not in AIR_BLOCKS for value in expectations)
        # A declared cube outside the export has definite absent geometry, not
        # an unknown block model, so it must fail rather than become pending.
        known = models_known
        good = adjacent and actual == expectations
        add(ident, 'unsupported' if not known else 'pass' if good else 'fail',
            f'Explicit full-cube contact: observed states {actual}, requested {expectations}, face adjacency={bool(adjacent)}. '
            'Non-cube or unidentified architectural contacts need a model-shape predicate.', expected=expectations,
            actual=actual, coordinates={'xyz':coords}, scope='explicit_full_cube_contact')

    from .roof_conformance import measure as measure_roof
    roof = measure_roof(path, plan=plan, section=section)
    required_roof = (plan.get('detail_profile') == 'reference_haussmann' or
                     plan.get('scheme', plan.get('facade')) == 'haussmann_apartment' or
                     plan.get('roof_profile') in ('mansard', 'steep_lower_shallow_crown'))
    for check in roof.get('checks', []):
        item = dict(check)
        item['required'] = bool(item.get('required', required_roof))
        item.setdefault('observation', item.get('reason', 'Roof predicate result.'))
        item.setdefault('reason', item['observation'])
        item.setdefault('coordinates', {})
        item.setdefault('scope', 'measured_roof_surface')
        checks.append(item)
    summary = _summary(checks)
    result = {'version': REPORT_VERSION, 'policy_id': POLICY_ID,
            'validator_sha256': validator_digest(),
            'section_version': section['version'], 'source': source, 'plan_sha256': plan_hash(plan),
            'stage': stage, 'status': _status(summary), 'summary': summary, 'checks': checks,
            'roof_evidence': roof, 'limitations': LIMITATIONS,
            'unscoped_requirements': ['semantic window schedule', 'window frame/sill/lintel roles and partial-model contact',
                                      'architectural course role schedule', 'functional storey/attic use'],
            'method': 'Read actual export states and hash-bound independent sections; compare only declared adapter predicates or explicit specifications.'}
    # Receipts must compare identically before and after actual JSON persistence:
    # section coordinates include tuples and roof histograms use integer keys.
    return json.loads(json.dumps(result, ensure_ascii=False))


def validate(report, schematic=None, plan=None, *, stage=None, recompute=True):
    """Reject stale/malformed receipts; with export+plan, verify by fresh measure."""
    if (isinstance(report, dict) and report.get('policy_id') == 'export-atlas-nw-stage-v1'
            or plan is not None and _plan(plan).get('detail_profile') == 'atlas_street1'):
        from .atlas_conformance import validate as validate_atlas
        return validate_atlas(report, schematic, plan, stage=stage, recompute=recompute)
    if (not isinstance(report, dict) or report.get('version') != REPORT_VERSION or report.get('policy_id') != POLICY_ID
            or report.get('validator_sha256') != validator_digest()):
        raise ValueError('Unsupported or stale architectural conformance receipt')
    checks = report.get('checks')
    if not isinstance(checks, list) or not checks or len({c.get('id') for c in checks if isinstance(c,dict)}) != len(checks):
        raise ValueError('Conformance checks need unique predicate IDs')
    for check in checks:
        if (not isinstance(check,dict) or not isinstance(check.get('id'),str) or not check['id']
                or check.get('status') not in ('pass','fail','unsupported') or type(check.get('required')) is not bool
                or not isinstance(check.get('observation'),str) or not check['observation'].strip()):
            raise ValueError('Malformed architectural conformance check')
    summary = _summary(checks)
    if summary != report.get('summary') or _status(summary) != report.get('status'):
        raise ValueError('Conformance summary disagrees with independent checks')
    if schematic is not None:
        path = Path(schematic)
        s = load_schematic(path)
        if (report.get('source',{}).get('sha256') != sha256(path.read_bytes()).hexdigest()
                or report.get('source',{}).get('voxel_state_hash') != s.voxel_state_hash()):
            raise ValueError('Conformance export hash changed')
    if plan is not None and report.get('plan_sha256') != plan_hash(plan):
        raise ValueError('Conformance plan hash changed')
    if stage is not None and report.get('stage') != stage:
        raise ValueError('Conformance stage changed')
    if recompute and schematic is not None and plan is not None:
        fresh = measure(schematic, plan, stage=stage or report['stage'])
        if fresh != report:
            raise ValueError('Conformance receipt differs from independently recomputed export predicates')
    return report
