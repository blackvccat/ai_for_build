"""Verify sourced facade states in the exported building, without granting game acceptance.

Stateful blocks are an inventory, not proof of a debug-stick construction method.
This scoped audit checks three explicitly declared reference methods and their
placements at each street residential opening. It does not measure model contact,
general architectural meaning, or survival after Minecraft block updates.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np

from .architecture import sensitive, split_state, state, state_category, transform_state
from .schematic import load_schematic


ROOT = Path(__file__).resolve().parents[2]
REPORT_VERSION = 1
CATEGORIES = ('thin_door_window', 'single_arm_wall', 'shaped_stair')
STREET_FACES = ('street_north', 'street_east')


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _manifest_hash(manifest):
    # Include the actual opening schedule and decorative exceptions, not merely
    # the claimed row counts. Changes to any of them require a fresh review.
    return hashlib.sha256(_canonical(manifest).encode('utf-8')).hexdigest()


def validator_digest():
    return hashlib.sha256((_hash(__file__) + _hash(Path(__file__).with_name('architecture.py'))).encode()).hexdigest()


def _xyz(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3 or any(type(n) is not int for n in value):
        raise ValueError('Coordinate must contain three integer x/y/z values')
    return tuple(value)


def _at(read, xyz):
    x, y, z = xyz
    h, d, w = read.volume.shape
    if not (0 <= x < w and 0 <= y < h and 0 <= z < d):
        raise ValueError('Coordinate lies outside the schematic')
    return read.id_to_state[int(read.volume[y, z, x])]


def _normal(value):
    name, props = split_state(value)
    return state(name, **props)


def special_category(value, *, decorative=False):
    """Return a scoped method; ordinary stairs/slabs/doors do not qualify."""
    name, props = split_state(value)
    if name.endswith('_door') and props.get('half') == 'lower' and decorative:
        return 'thin_door_window'
    if name.endswith('_wall') and props.get('up') == 'false':
        arms = [props.get(direction) for direction in ('north', 'east', 'south', 'west')]
        if all(arm in ('none', 'low', 'tall') for arm in arms) and sum(arm != 'none' for arm in arms) == 1:
            return 'single_arm_wall'
    if (name.endswith('_stairs') and props.get('half') == 'top'
            and props.get('shape') in ('inner_left', 'inner_right', 'outer_left', 'outer_right')):
        return 'shaped_stair'
    return None


def _source_path(value, roots):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Source path is missing')
    path = Path(value)
    if not path.is_absolute():
        path = ROOT.parent / path
    path = path.resolve()
    if not any(path.is_relative_to(root) for root in roots):
        raise ValueError('Source is outside the read-only reference roots')
    if not path.is_file() or path.suffix != '.schem':
        raise ValueError('Source must be an existing reference schematic')
    return path


def _record(source_id, records):
    if records is not None:
        if source_id not in records:
            raise ValueError('Unknown audited reference sample')
        return records[source_id]
    if not isinstance(source_id, str) or not source_id.startswith('v3:'):
        raise ValueError('Source state requires an audited v3 reference sample')
    ident = source_id[3:]
    if not ident or Path(ident).name != ident or '/' in ident or '\\' in ident:
        raise ValueError('Invalid reference sample id')
    folder = ROOT / 'knowledge/library-v3/reference-techniques' / ident
    path = folder / 'record.json'
    if not path.is_file():
        raise ValueError('Unknown audited reference sample')
    data = json.loads(path.read_text(encoding='utf-8'))
    return {**data, '_sample_path': str(folder / 'detail.schem'), '_record_path': str(path)}


def _footprint(read):
    # The current adapter has a solid foundation at its lowest occupied y.
    # Architectural conformance independently verifies its supported topology.
    ys = np.flatnonzero(read.nonair_mask().any(axis=(1, 2)))
    if not len(ys):
        raise ValueError('Export has no foundation')
    zs, xs = np.where(read.nonair_mask()[int(ys[0])])
    return int(xs.min()), int(xs.max()), int(zs.min()), int(zs.max())


def _placement(row, opening, footprint):
    face = opening.get('face')
    if face not in STREET_FACES or row.get('face') != face:
        raise ValueError('Source placement face differs from its street opening')
    floor = opening.get('floor')
    if type(floor) is not int or floor <= 0 or row.get('storey') != floor or opening.get('kind') != 'window':
        raise ValueError('Source placement must belong to the stated residential window storey')
    u0, y0, width, height = (opening.get(k) for k in ('u', 'y', 'width', 'height'))
    if any(type(n) is not int for n in (u0, y0, width, height)) or width <= 0 or height <= 0:
        raise ValueError('Street opening has no supported integer schedule')
    x, y, z = _xyz(row['target_xyz'])
    x0, x1, z0, z1 = footprint
    u, depth = (x, z - z0) if face == 'street_north' else (z, x1 - x)
    role = row.get('role')
    if role == 'thin_door_window':
        okay = depth == 1 and u0 <= u < u0 + width and y0 <= y < y0 + height
    elif role == 'single_arm_wall':
        okay = depth == -1 and u in (u0 - 1, u0 + width) and y0 <= y < y0 + height
    elif role == 'shaped_stair':
        okay = depth == -1 and u0 - 1 <= u <= u0 + width and y == y0 + height
    else:
        okay = False
    if not okay:
        raise ValueError('Source state is outside the declared window construction position')
    return u, y


def audit(schematic, manifest, required=False, *, source_roots=None, source_records=None):
    """Double-read source/export and return a hash-bound scoped evidence report.

    ``source_roots`` and ``source_records`` are trusted injection points for
    isolated test fixtures. Production calls use the project reference roots and
    audited v3 sample records. ``required=True`` enforces all three declared
    methods at every residential opening on the two street facades.
    """
    path = Path(schematic).resolve()
    read = load_schematic(path)
    roots = [Path(p).resolve() for p in (source_roots if source_roots is not None else
             (ROOT.parent / '巴黎建筑素材', ROOT.parent / '巴黎建筑修改版', ROOT.parent / '窗',
              ROOT / '_incoming_schematics'))]
    errors, checked = [], []
    sources, samples = {}, {}
    rows = manifest.get('source_state_audit', [])
    if not isinstance(rows, list):
        errors.append('source_state_audit must be a list')
        rows = []
    requirements = manifest.get('source_state_requirements')
    if required:
        if not isinstance(requirements, dict):
            errors.append('Final tier requires explicit source state requirements')
        else:
            categories = requirements.get('required_categories')
            faces = requirements.get('required_faces')
            if (not isinstance(categories, list) or any(not isinstance(v, str) for v in categories)
                    or len(categories) != len(CATEGORIES) or set(categories) != set(CATEGORIES)):
                errors.append('Final source requirements must name all three scoped methods')
            if (not isinstance(faces, list) or any(not isinstance(v, str) for v in faces)
                    or len(faces) != len(STREET_FACES) or set(faces) != set(STREET_FACES)):
                errors.append('Final source requirements must cover both street facades')
            if requirements.get('coverage') != 'all_street_residential_openings':
                errors.append('Final source requirements need the residential opening coverage schedule')
        if not rows:
            errors.append('No source special states survive in the final export')
    openings = manifest.get('openings', [])
    if not isinstance(openings, list):
        errors.append('Openings must be a supported schedule')
        openings = []
    decorative = {}
    declarations = manifest.get('decorative_doors', [])
    if not isinstance(declarations, list):
        errors.append('Decorative door declarations must be a list')
        declarations = []
    for entry in declarations:
        try:
            coordinate = _xyz(entry['xyz'])
            if coordinate in decorative:
                raise ValueError('Duplicate decorative door coordinate')
            decorative[coordinate] = _normal(entry['state'])
        except (ValueError, TypeError, KeyError) as error:
            errors.append('Invalid decorative door declaration: ' + str(error))
    footprint = _footprint(read)
    seen = set()
    coverage = {}
    for index, row in enumerate(rows):
        result = {'index': index, 'status': 'FAIL'}
        try:
            if not isinstance(row, dict):
                raise ValueError('Audit row is not an object')
            coordinate = _xyz(row.get('target_xyz'))
            if coordinate in seen:
                raise ValueError('Duplicate target source state coordinate')
            seen.add(coordinate)
            source_xyz = _xyz(row.get('source_xyz'))
            source = _source_path(row.get('source_path'), roots)
            if source == path:
                raise ValueError('Generated export cannot be its own reference source')
            if str(source) not in sources:
                sources[str(source)] = {'read': load_schematic(source), 'sha256': _hash(source)}
            original = _at(sources[str(source)]['read'], source_xyz)
            if row.get('source_sha256') != sources[str(source)]['sha256']:
                raise ValueError('Reference source hash changed')
            if not isinstance(row.get('original_state'), str) or _normal(row['original_state']) != _normal(original):
                raise ValueError('Source coordinate does not contain the claimed original state')
            record = _record(row.get('source_id'), source_records)
            if _source_path(record.get('source'), roots) != source or record.get('source_sha256') != row['source_sha256']:
                raise ValueError('Audit source does not match its independently recorded reference sample')
            local = _xyz(row.get('source_local_xyz'))
            origin = _xyz(record.get('clean_origin_source_xyz'))
            if tuple(origin[i] + local[i] for i in range(3)) != source_xyz:
                raise ValueError('Source sample local coordinate differs from its original source coordinate')
            sample_path = Path(record['_sample_path']).resolve()
            if str(sample_path) not in samples:
                samples[str(sample_path)] = {'read': load_schematic(sample_path), 'sha256': _hash(sample_path)}
            if row.get('sample_sha256') != samples[str(sample_path)]['sha256']:
                raise ValueError('Audited source sample hash changed')
            sample_state = _at(samples[str(sample_path)]['read'], local)
            # The only audited version rename relevant to these reference crops.
            original_name, original_props = split_state(original)
            migrated = state('minecraft:iron_chain' if original_name == 'minecraft:chain' else original_name,
                             **original_props)
            if _normal(sample_state) != _normal(migrated):
                raise ValueError('Audited sample differs from its original source state')
            turns, mirror = row.get('turns'), row.get('mirror')
            if type(turns) is not int or turns not in range(4) or type(mirror) is not bool:
                raise ValueError('State transform requires explicit turns 0..3 and mirror boolean')
            outside = str(record.get('outside', '')).split('/')[0]
            if outside not in ('north', 'east', 'south', 'west'):
                raise ValueError('Source sample outside orientation is unsupported')
            wanted = {'street_north': 'north', 'street_east': 'east'}.get(row.get('face'))
            direction = ('north', 'east', 'south', 'west')[
                (('north', 'east', 'south', 'west').index(outside) + turns) % 4]
            if mirror:
                # A local-x mirror flips east/west before the rotation.
                outside = {'east': 'west', 'west': 'east'}.get(outside, outside)
                direction = ('north', 'east', 'south', 'west')[
                    (('north', 'east', 'south', 'west').index(outside) + turns) % 4]
            if direction != wanted:
                raise ValueError('Source outside orientation does not rotate onto the stated facade')
            expected = transform_state(sample_state, turns=turns, mirror=mirror)
            actual = _at(read, coordinate)
            if not isinstance(row.get('transformed_state'), str) or _normal(row['transformed_state']) != expected:
                raise ValueError('Claimed transformed state differs from the allowed source transform')
            if _normal(actual) != expected:
                raise ValueError('Sourced state is missing, overwritten, or changed in the export')
            role = row.get('role')
            is_door = role == 'thin_door_window'
            if is_door and decorative.get(coordinate) != expected:
                raise ValueError('Thin source door must be explicitly declared as decorative window joinery')
            category = special_category(actual, decorative=is_door)
            name, props = split_state(actual)
            # A complete shaped header also contains straight center fillers.
            # Preserve and verify them, but never count them as special shapes or
            # allow a straight-only header to satisfy the shaped-stair predicate.
            ordinary_header = (role == 'shaped_stair' and name.endswith('_stairs')
                               and props.get('half') == 'top' and props.get('shape') == 'straight')
            if not ordinary_header and (category is None or role != category):
                raise ValueError('Ordinary state or incorrect role cannot stand in for a source special method')
            opening_id = row.get('opening_id')
            if type(opening_id) is not int or not 0 <= opening_id < len(openings):
                raise ValueError('Source method has no real residential opening index')
            if not isinstance(openings[opening_id], dict):
                raise ValueError('Source method points to an invalid opening schedule row')
            u, y = _placement(row, openings[opening_id], footprint)
            if category is not None:
                coverage.setdefault(opening_id, {}).setdefault(category, set()).add((u, y))
            result.update(status='PASS', category=category or 'ordinary_header', method_role=role,
                          face=row['face'], storey=row['storey'],
                          opening_id=opening_id, source_path=str(source), source_xyz=list(source_xyz),
                          target_xyz=list(coordinate), state=actual)
        except (ValueError, TypeError, KeyError, OSError, IndexError) as error:
            result['reason'] = str(error)
            errors.append('Source state row %d: %s' % (index, error))
        checked.append(result)
    expected_openings = [(index, opening) for index, opening in enumerate(openings)
                         if isinstance(opening, dict) and opening.get('face') in STREET_FACES
                         and opening.get('kind') == 'window' and type(opening.get('floor')) is int
                         and opening['floor'] > 0]
    coverage_rows = []
    for index, opening in expected_openings:
        covered = coverage.get(index, {})
        missing = [category for category in CATEGORIES if not covered.get(category)]
        try:
            u, y, width, height = (opening[k] for k in ('u', 'y', 'width', 'height'))
            if any(type(n) is not int for n in (u, y, width, height)) or not 0 < width <= 32 or not 0 < height <= 32:
                raise ValueError('Residential window dimensions are unsupported')
            door_surface = {(uu, yy) for uu in range(u, u + width) for yy in range(y, y + height)}
            missing_door_cells = len(door_surface - covered.get('thin_door_window', set()))
        except (ValueError, KeyError, TypeError):
            missing_door_cells = None
            missing.append('supported_window_schedule')
        okay = not missing and missing_door_cells == 0
        coverage_rows.append({'opening_id': index, 'face': opening['face'], 'storey': opening['floor'],
                              'status': 'PASS' if okay else 'FAIL', 'missing_categories': missing,
                              'missing_thin_window_cells': missing_door_cells,
                              'matched_by_category': {k: len(v) for k, v in covered.items()}})
        if required and not okay:
            errors.append('Residential opening %d has incomplete source-method coverage' % index)
    if required and {o['face'] for _, o in expected_openings} != set(STREET_FACES):
        errors.append('Export schedule has no residential windows on both street facades')
    counts = Counter()
    stateful = Counter()
    for palette_id, value in enumerate(read.id_to_state):
        amount = int((read.volume == palette_id).sum())
        if amount and sensitive(value):
            stateful[state_category(value)] += amount
    counts.update(row['category'] for row in checked if row['status'] == 'PASS' and row['category'] in CATEGORIES)
    status = 'FAIL' if errors else ('PASS' if rows else 'NOT_REQUIRED')
    return {'report_version': REPORT_VERSION, 'status': status, 'required': bool(required),
            'source': {'path': str(path), 'sha256': _hash(path), 'voxel_state_hash': read.voxel_state_hash()},
            'manifest_hash': _manifest_hash(manifest), 'validator_digest': validator_digest(),
            'reference_sources': [{'path': p, 'sha256': r['sha256']} for p, r in sorted(sources.items())],
            'reference_samples': [{'path': p, 'sha256': r['sha256']} for p, r in sorted(samples.items())],
            'declared': len(rows), 'matched': sum(r['status'] == 'PASS' for r in checked),
            'matched_ordinary_header_cells': sum(r.get('category') == 'ordinary_header' for r in checked),
            'source_special_categories': dict(counts), 'stateful_inventory': dict(stateful),
            'rows': checked, 'opening_coverage': coverage_rows, 'failures': errors,
            'scope': 'Source state preservation and declared street-window placements only; not model contact or game stability.',
            'game_acceptance': 'PENDING'}


measure = audit


def validate(report, schematic, manifest, required=False, *, recompute=True, **fixture_options):
    """Reject stale/edited reports; promotion callers always recompute source facts."""
    if report.get('report_version') != REPORT_VERSION or report.get('required') != bool(required):
        raise ValueError('Source state report has the wrong version or stage requirement')
    if report.get('manifest_hash') != _manifest_hash(manifest) or report.get('validator_digest') != validator_digest():
        raise ValueError('Source state manifest or validator changed')
    if report.get('source', {}).get('sha256') != _hash(schematic):
        raise ValueError('Source state export changed')
    if recompute:
        current = audit(schematic, manifest, required=required, **fixture_options)
        if _canonical(current) != _canonical(report):
            raise ValueError('Source state report differs from independently recomputed evidence')
    return report
