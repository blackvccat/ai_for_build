"""Classify a regular mansard from exported voxels, with located counterexamples.

This is a bounded instrument for the current rectangular / NE-chamfer roof. It
does not infer a surface from the generator's roof formula or manifest counts.
Every sampled height is an actual roof-family cell. Perimeter populations locate
the dominant shell; isolated higher cells remain separately visible as possible
appendages. Unsupported populations cannot grant conformance.
"""
from collections import Counter
from hashlib import sha256
from pathlib import Path

import numpy as np

from .schematic import base_block, load_schematic


REPORT_VERSION = 1
POLICY = {
    'minimum_profile_samples': 7,
    'minimum_dominant_fraction': .5,
    'minimum_surface_coverage': .7,
    'minimum_lower_slope': 1.25,
    'minimum_upper_slope': .1,
    'maximum_upper_slope': .75,
    'minimum_slope_ratio': 2.,
    'minimum_upper_rise': 1.,
    'minimum_rmse_improvement': .2,
    'maximum_segmented_rmse': .65,
    'maximum_ridge_width_cells': 3,
    'maximum_local_appendage_width_cells': 3,
}


def _mode(values):
    counts = Counter(int(v) for v in values)
    if not counts:
        return None, 0., {}
    # A tie is explicit in the histogram. Choosing the lower actual height keeps
    # a narrow high crest from becoming the shell without majority evidence.
    height, count = min(counts.items(), key=lambda item: (-item[1], item[0]))
    return height, count / sum(counts.values()), dict(sorted(counts.items()))


def classify_profile(heights):
    """Fit one measured eave-to-ridge profile; never fill missing observations."""
    values = list(heights)
    if len(values) < POLICY['minimum_profile_samples'] or any(v is None for v in values):
        return {'status': 'unsupported', 'classification': 'insufficient_profile',
                'reason': 'A complete measured eave-to-ridge profile needs at least seven columns.'}
    y = np.asarray(values, dtype=float)
    x = np.arange(len(y), dtype=float)
    linear = np.column_stack((np.ones(len(x)), x))
    linear_fit = np.linalg.lstsq(linear, y, rcond=None)[0]
    linear_rmse = float(np.sqrt(np.mean((linear @ linear_fit - y) ** 2)))
    alternatives = []
    for split in range(2, len(y)-2):
        design = np.column_stack((np.ones(len(x)), np.minimum(x, split), np.maximum(x-split, 0)))
        fitted = np.linalg.lstsq(design, y, rcond=None)[0]
        error = float(np.sqrt(np.mean((design @ fitted-y) ** 2)))
        alternatives.append((error, split, fitted))
    error, split, fitted = min(alternatives, key=lambda item: (item[0], item[1]))
    lower, upper = float(fitted[1]), float(fitted[2])
    ratio = lower / upper if upper > 0 else None
    upper_rise = upper * (len(y)-1-split)
    improvement = linear_rmse-error
    predicates = {
        'profile_does_not_descend_inward': bool(np.min(np.diff(y)) >= -1),
        'lower_is_steep': lower >= POLICY['minimum_lower_slope'],
        'upper_is_shallow_and_rising': POLICY['minimum_upper_slope'] <= upper <= POLICY['maximum_upper_slope'],
        'slope_contrast': ratio is not None and ratio >= POLICY['minimum_slope_ratio'],
        'upper_has_real_rise': upper_rise >= POLICY['minimum_upper_rise'],
        'break_improves_linear_fit': improvement >= POLICY['minimum_rmse_improvement'],
        'segmented_profile_fits': error <= POLICY['maximum_segmented_rmse'],
    }
    passed = all(predicates.values())
    plateau = 1
    for height in reversed(y[:-1]):
        if height != y[-1]:
            break
        plateau += 1
    if passed:
        classification = 'steep_lower_shallow_upper'
    elif np.ptp(y) == 0 or upper <= POLICY['minimum_upper_slope'] or plateau >= 3:
        classification = 'flat_or_broad_plateau'
    elif not predicates['lower_is_steep'] or not predicates['slope_contrast'] or not predicates['break_improves_linear_fit']:
        classification = 'linear_or_insufficient_slope_break'
    else:
        classification = 'irregular_profile'
    failed = [name for name, passed in predicates.items() if not passed]
    return {'status': 'pass' if passed else 'fail', 'classification': classification,
            'break_distance_cells': split, 'lower_slope': round(lower, 4),
            'upper_slope': round(upper, 4), 'slope_ratio': round(ratio, 4) if ratio is not None else None,
            'upper_rise': round(upper_rise, 4), 'linear_slope': round(float(linear_fit[1]), 4),
            'linear_rmse': round(linear_rmse, 4), 'segmented_rmse': round(error, 4),
            'rmse_improvement': round(improvement, 4), 'terminal_plateau_samples': plateau,
            'predicates': predicates, 'failed_predicates': failed,
            'reason': (f'Measured lower slope {lower:.2f} and upper slope {upper:.2f} cells/column; '
                       f'break at column {split}; segmented RMSE {error:.2f} versus linear {linear_rmse:.2f}. '
                       + ('A steep-to-shallow break is present.' if passed else
                          'Required mansard geometry is absent: '+', '.join(failed)+'.'))}


def _check(status, reason, actual=None, coordinates=None):
    return {'id': 'roof/mansard_profile', 'status': status, 'reason': reason,
            'expected': {'profile': 'steep lower slope, distinct break, rising shallow upper slope, narrow ridge',
                         'policy': dict(POLICY)},
            'actual': actual, 'coordinates': coordinates or []}


def _components(points):
    remaining, components = set(points), []
    while remaining:
        first = remaining.pop()
        component, pending = {first}, [first]
        while pending:
            x, z = pending.pop()
            for neighbour in ((x-1, z), (x+1, z), (x, z-1), (x, z+1)):
                if neighbour in remaining:
                    remaining.remove(neighbour)
                    component.add(neighbour)
                    pending.append(neighbour)
        components.append(component)
    return components


def measure(schematic_path, plan=None, section=None):
    """Return one independent roof check and its hash-bound measured evidence.

    ``plan`` is accepted for the architectural-conformance interface but does not
    supply roof heights, eave coordinates or classifications. ``section`` may
    reuse facade_section's independently measured floor / footprint proxies;
    its source digest must match the current export.
    """
    path = Path(schematic_path)
    s = load_schematic(path)
    source = {'path': str(path.resolve()), 'sha256': sha256(path.read_bytes()).hexdigest(),
              'voxel_state_hash': s.voxel_state_hash()}
    if section is None:
        from .facade_section import measure as measure_section
        section = measure_section(path)
    if section.get('source', {}).get('sha256') != source['sha256']:
        raise ValueError('Roof section evidence is stale: schematic SHA-256 differs.')
    if section.get('source', {}).get('voxel_state_hash') != source['voxel_state_hash']:
        raise ValueError('Roof section evidence does not match the exported voxel states.')
    result = {'version': REPORT_VERSION, 'source': source,
              'method': 'Dominant exported roof-family heights at equal distance from measured foundation edges; '
                        'actual cells near each dominant height form the shell, higher cells remain located separately. '
                        'Continuous two-segment regression tests steep/shallow contrast; a short-axis transect measures ridge width.',
              'limitations': [
                  'Supports regular rectangular or NE-chamfered hipped roofs in the current deepslate/blackstone palette.',
                  'Foundation and broad floor plates are export measurements; floor plates are storey proxies.',
                  'Population separation identifies local elevated volumes, not semantic proof that they are chimneys or dormers.',
                  'A broad attached volume that replaces most observations at an eave distance remains part of the measured geometry.',
                  'Heights are voxel cells, not sub-block slab/stair model surfaces; no style or game acceptance is granted.',
              ], 'checks': []}
    if (section.get('status') != 'measured' or not section.get('floors_y') or
            not section.get('footprint', {}).get('supported_pattern')):
        result['checks'] = [_check('unsupported', 'Cannot locate a supported foundation and floor proxies from the export.')]
        return result
    x0, z0, x1, z1 = section['footprint']['bounds_xz']
    floor = int(section['floors_y'][-1])
    roof_ids = [i for i, state in enumerate(s.id_to_state)
                if 'deepslate' in base_block(state) or 'blackstone' in base_block(state)]
    roof = np.isin(s.volume, roof_ids)
    roof[:floor+1] = False
    tops = np.max(np.where(roof, np.arange(s.height)[:, None, None], -1), axis=0)
    footprint = s.nonair_mask()[0, z0:z1+1, x0:x1+1]
    zz, xx = np.mgrid[z0:z1+1, x0:x1+1]
    distances = np.minimum.reduce((xx-x0, x1-xx, zz-z0, z1-zz))
    rings = []
    for distance in range(int(distances.max())+1):
        indices = np.argwhere((distances == distance) & footprint)
        located = [[int(x+x0), int(tops[z+z0, x+x0]), int(z+z0)]
                   for z, x in indices if tops[z+z0, x+x0] >= 0]
        mode, confidence, histogram = _mode(point[1] for point in located)
        rings.append({'distance_cells': distance, 'dominant_height_y': mode,
                      'dominant_fraction': round(confidence, 4), 'height_counts': histogram,
                      'observed_columns': len(located), 'footprint_columns': len(indices),
                      'dominant_coordinates_xyz': [p for p in located if p[1] == mode]})
    result['eave_distance_profiles'] = rings
    ambiguous = [row for row in rings if row['dominant_height_y'] is None or
                 row['dominant_fraction'] < POLICY['minimum_dominant_fraction']]
    if ambiguous:
        result['checks'] = [_check('unsupported', 'No dominant roof shell at measured eave distances; missing or competing surfaces.',
                                  {'ambiguous_distances': [row['distance_cells'] for row in ambiguous]})]
        return result
    main = np.full((z1-z0+1, x1-x0+1), -1, dtype=int)
    appendages, interruptions, missing = [], [], []
    for z, x in np.argwhere(footprint):
        u, v, distance = int(x+x0), int(z+z0), int(distances[z, x])
        observed = int(tops[v, u])
        reference = rings[distance]['dominant_height_y']
        cells = np.flatnonzero(roof[:, v, u])
        nearby = [int(y) for y in cells if abs(int(y)-reference) <= 1]
        if nearby:
            selected = min(nearby, key=lambda y: (abs(y-reference), y))
            main[z, x] = selected
            if observed > selected:
                appendages.append({'coordinate_xz': [u, v], 'shell_y': selected,
                                   'top_y': observed, 'above_shell_cells_y': [int(y) for y in cells if y > selected]})
        elif observed < 0:
            missing.append([u, v])
        else:
            interruptions.append({'coordinate_xz': [u, v], 'observed_top_y': observed,
                                  'dominant_ring_y': reference})
    coverage = float(np.count_nonzero(main >= 0) / np.count_nonzero(footprint))
    result['surface'] = {'bounds_xz': [x0, z0, x1, z1], 'last_floor_y': floor,
                         'height_y_z_x': [[None if y < 0 else int(y) for y in line] for line in main],
                         'measured_coverage': round(coverage, 4),
                         'elevated_columns': appendages, 'interrupted_columns': interruptions,
                         'missing_columns_xz': missing}
    elevated_positions = {tuple(row['coordinate_xz']) for row in appendages}
    elevated_positions.update(tuple(row['coordinate_xz']) for row in interruptions
                              if row['observed_top_y'] > row['dominant_ring_y'])
    broad = []
    for component in _components(elevated_positions):
        xs, zs = zip(*component)
        width, depth = max(xs)-min(xs)+1, max(zs)-min(zs)+1
        if min(width, depth) > POLICY['maximum_local_appendage_width_cells']:
            broad.append({'bounds_xz': [min(xs), min(zs), max(xs), max(zs)],
                          'columns': len(component)})
    if broad:
        result['checks'] = [_check('unsupported',
            'A broad competing roof volume cannot be safely separated as a local chimney/dormer; shell classification remains unsupported.',
            {'competing_regions': broad})]
        return result
    if coverage < POLICY['minimum_surface_coverage']:
        result['checks'] = [_check('unsupported', 'Too little of the actual shell survives population separation.',
                                  {'measured_coverage': round(coverage, 4)})]
        return result
    profiles = {}
    for face in ('west', 'east', 'north', 'south'):
        samples = []
        for distance in range(len(rings)):
            if face in ('west', 'east'):
                column = distance if face == 'west' else x1-x0-distance
                positions = [(z, column) for z in range(distance, z1-z0-distance+1)]
            else:
                row = distance if face == 'north' else z1-z0-distance
                positions = [(row, x) for x in range(distance, x1-x0-distance+1)]
            points = [[int(x+x0), int(main[z, x]), int(z+z0)]
                      for z, x in positions if main[z, x] >= 0]
            height, confidence, histogram = _mode(point[1] for point in points)
            samples.append({'distance_cells': distance, 'height_y': height,
                            'support_fraction': round(confidence, 4), 'height_counts': histogram,
                            'coordinates_xyz': [p for p in points if p[1] == height]})
        profiles[face] = {'samples': samples, **classify_profile(row['height_y'] for row in samples)}
    result['faces'] = profiles
    # The long axis naturally has a long ridge: only its transverse width is a
    # conformance dimension. Hipped end plateaux must not count as ridge width.
    transverse_axis = 'x' if x1-x0 <= z1-z0 else 'z'
    transect = []
    size = x1-x0+1 if transverse_axis == 'x' else z1-z0+1
    for coordinate in range(size):
        distance = min(coordinate, size-1-coordinate)
        positions = ([(z, coordinate) for z in range(distance, z1-z0-distance+1)]
                     if transverse_axis == 'x' else
                     [(coordinate, x) for x in range(distance, x1-x0-distance+1)])
        points = [[int(x+x0), int(main[z, x]), int(z+z0)]
                  for z, x in positions if main[z, x] >= 0]
        height, _, _ = _mode(point[1] for point in points)
        transect.append({'coordinate': coordinate+(x0 if transverse_axis == 'x' else z0),
                         'height_y': height, 'coordinates_xyz': [p for p in points if p[1] == height]})
    peak = max((row['height_y'] for row in transect if row['height_y'] is not None), default=None)
    ridge_coordinates = [row['coordinate'] for row in transect if row['height_y'] == peak]
    ridge_width = max(ridge_coordinates)-min(ridge_coordinates)+1 if ridge_coordinates else 0
    ridge = {'transverse_axis': transverse_axis, 'height_y': peak, 'width_cells': ridge_width,
             'coordinates': ridge_coordinates, 'transect': transect}
    result['ridge'] = ridge
    actual = {'faces': {face: {k: v for k, v in data.items() if k != 'samples'}
                        for face, data in profiles.items()},
              'ridge_width_cells': ridge_width, 'elevated_column_count': len(appendages),
              'interrupted_column_count': len(interruptions), 'missing_column_count': len(missing)}
    unsupported = [face for face, data in profiles.items() if data['status'] == 'unsupported']
    failed = [face for face, data in profiles.items() if data['status'] == 'fail']
    ridge_failed = ridge_width > POLICY['maximum_ridge_width_cells']
    if unsupported:
        status, reason = 'unsupported', 'Incomplete measured profiles on '+', '.join(unsupported)+'.'
    elif failed or ridge_failed:
        status = 'fail'
        reason = ' '.join(face+': '+profiles[face]['reason'] for face in failed)
        if ridge_failed:
            reason += f' The measured transverse ridge/plateau spans {ridge_width} cells (maximum 3).'
    else:
        status = 'pass'
        reason = (f'All four exported main-shell profiles contain a steep-to-shallow break; '
                  f'transverse ridge spans {ridge_width} cells. '
                  f'{len(appendages)} elevated columns are reported separately rather than treated as slope spikes.')
    coordinates = [point for face in profiles.values() for row in face['samples']
                   if row['distance_cells'] == face.get('break_distance_cells') for point in row['coordinates_xyz']]
    result['checks'] = [_check(status, reason.strip(), actual, coordinates)]
    return result
