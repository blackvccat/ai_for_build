"""Design rules for the atlas corner apartment, expressed before piece assembly.

The layout contains bay indices, architectural roles and relative projection
distances. It has no source-piece identifiers, block names or scene coordinates.
The assembler owns source selection, physical placement and junction repair.

``flat_baseline`` is an explicit compatibility mode: its empty chimney-anchor
list delegates the old fixed placement to the assembler. It adds no strategic
plants or finial; plants already present in source pieces remain source content.
Neither this contract nor its validation establishes visual or game acceptance.
"""
from collections.abc import Mapping


SCHEMA_VERSION = 2
MODES = ('grouped_pavilions', 'flat_baseline')
WINGS = ('north', 'west')
DEFAULT_RHYTHM = (4, 5, 5, 4)
_GROUP_ROLES = ('near_recess', 'central_pavilion', 'middle_recess', 'end_pavilion')


def _integer(value, label, minimum=None):
    if type(value) is not int or (minimum is not None and value < minimum):
        suffix = '' if minimum is None else ' >= %d' % minimum
        raise ValueError('composition: %s must be an integer%s' % (label, suffix))
    return value


def _keys(value, expected, label):
    if not isinstance(value, Mapping) or set(value) != set(expected):
        raise ValueError('composition: %s requires fields %s' % (label, ', '.join(expected)))


def _read_plan(plan, name, default=None):
    return plan.get(name, default) if isinstance(plan, Mapping) else getattr(plan, name, default)


def _mode(value):
    if value not in MODES:
        raise ValueError('composition: unknown mode %r; choose %s' % (value, ', '.join(MODES)))
    return value


def _rhythm(pattern, phase):
    if not isinstance(pattern, (tuple, list)) or not pattern:
        raise ValueError('composition: rhythm must be a nonempty pitch sequence')
    for pitch in pattern:
        _integer(pitch, 'rhythm pitch', 4)
        if pitch > 6:
            raise ValueError('composition: rhythm pitches must be between four and six')
    _integer(phase, 'rhythm phase', 0)
    if phase >= len(pattern):
        raise ValueError('composition: rhythm phase must index the pitch sequence')
    return list(pattern), phase


def wing_extra_width(bay_count, *, mode='grouped_pavilions', phase=0, rhythm=DEFAULT_RHYTHM):
    """Reserve span before choosing how many bays fit in a plan dimension.

    Four groups create three boundary piers with a pure two-cell gap between
    four-cell bays. Each boundary pitch is therefore six; the extra depends on
    the original pitch and phase. Two further cells reserve the whole-scene
    origin shift, so projected source cornices remain inside the plot budget.
    """
    _integer(bay_count, 'bay_count', 4)
    pattern, phase = _rhythm(rhythm, phase)
    if _mode(mode) == 'flat_baseline':
        return 0
    focal = (bay_count - 1) // 2
    return 2 + sum(6 - pattern[(phase + index) % len(pattern)]
                   for index in (focal - 1, focal, bay_count - 2))


def _wing(count, mode, phase, rhythm):
    grouped = mode == 'grouped_pavilions'
    # Even widths choose the central bay nearer the corner. For four bays this
    # leaves a complete recessed bay between the centre and the terminal bay.
    focal = (count - 1) // 2 if grouped else None
    if grouped:
        group_specs = (
            ('near_recess', list(range(focal))),
            ('central_pavilion', [focal]),
            ('middle_recess', list(range(focal + 1, count - 1))),
            ('end_pavilion', [count - 1]),
        )
    else:
        group_specs = (('flat', list(range(count))),)
    groups = [{'id': 'group-%d' % i, 'role': role, 'bays': indices}
              for i, (role, indices) in enumerate(group_specs)]
    bays = []
    for group in groups:
        pavilion = group['role'] in ('central_pavilion', 'end_pavilion')
        for index in group['bays']:
            role = 'corner_transition' if index == 0 else (
                group['role'] if pavilion else 'recessed')
            bays.append({
                'index': index, 'group': group['id'], 'role': role,
                'projection': 2 if pavilion else 0,
                'dormer_grade': 'none' if index == 0 else ('pavilion' if pavilion else 'ordinary'),
                'window_grade': 'emphasized' if pavilion else 'standard',
                'plant_accent': pavilion,
            })
    boundaries = [{'after_bay': group['bays'][-1], 'width': 2,
                   'extra_pitch': 6 - rhythm[(phase + group['bays'][-1]) % len(rhythm)]}
                  for group in groups[:-1]]
    chimneys = ([{'bay': focal, 'target_flues': 5, 'group_role': 'central_pavilion'},
                 {'bay': count - 1, 'target_flues': 5, 'group_role': 'end_pavilion'}]
                if grouped else [])
    return {
        'bay_count': count, 'focal_bay': focal, 'groups': groups, 'bays': bays,
        'pier_boundaries': boundaries,
        'extra_pitch_total': sum(row['extra_pitch'] for row in boundaries),
        'extra_width': wing_extra_width(count, mode=mode, phase=phase, rhythm=rhythm),
        'chimney_policy': 'focal_clusters' if grouped else 'legacy_fixed',
        'chimney_anchors': chimneys,
    }


def composition_for(plan, bays_north, bays_west, *, mode=None, phase=None, rhythm=DEFAULT_RHYTHM):
    """Return a JSON-serializable, validated composition for a corner plan.

    ``mode`` overrides ``plan.composition_profile``. If neither is supplied,
    the design uses grouped pavilions. Counts are provided by the assembly
    planner after reserving ``wing_extra_width`` inside the width/depth budget.
    """
    mode = _mode(mode if mode is not None else (
        _read_plan(plan, 'composition_profile') or 'grouped_pavilions'))
    if _read_plan(plan, 'form') != 'corner_house':
        raise ValueError('composition: the turret composition requires corner_house')
    _integer(bays_north, 'north bay_count', 5)
    _integer(bays_west, 'west bay_count', 4)
    subject = {name: _read_plan(plan, name) for name in ('form', 'width', 'depth', 'seed')}
    _integer(subject['width'], 'plan.width', 1)
    _integer(subject['depth'], 'plan.depth', 1)
    _integer(subject['seed'], 'plan.seed')
    rhythm, _ = _rhythm(rhythm, 0)
    rhythm, phase = _rhythm(rhythm, subject['seed'] % len(rhythm) if phase is None else phase)
    grouped = mode == 'grouped_pavilions'
    layout = {
        'schema_version': SCHEMA_VERSION, 'mode': mode, 'plan': subject,
        'rhythm': {'pattern': rhythm, 'phase': phase},
        'wings': {'north': _wing(bays_north, mode, phase, rhythm),
                  'west': _wing(bays_west, mode, phase, rhythm)},
        'corner': {'family': 'turret', 'projection': 1 if grouped else 0,
                   'origin_margin': 2 if grouped else 0, 'finial': grouped,
                   'visual_rank': 1},
        'color_strategy': 'source_plants_by_group' if grouped else 'legacy_source_plants',
        'limitations': ['shutter_color_variants_unavailable'],
    }
    validate_composition(layout)
    return layout


def validate_composition(layout):
    """Reject inconsistent or unsupported design contracts before writing blocks.

    This checks group continuity and coverage, the pavilion/recess hierarchy,
    agreement between facade and roof grades, grouped chimney intentions,
    accent placement and the declared width reserve. It does not measure the
    resulting schematic or assert that the chosen source implements a grade.
    """
    _keys(layout, ('schema_version', 'mode', 'plan', 'rhythm', 'wings', 'corner',
                   'color_strategy', 'limitations'), 'layout')
    if type(layout['schema_version']) is not int or layout['schema_version'] not in (1, SCHEMA_VERSION):
        raise ValueError('composition: unsupported schema_version')
    # Persisted version-1 candidates retain their original one-cell geometry.
    # New layouts reserve the full two-cell relief, including source cornices.
    relief = 1 if layout['schema_version'] == 1 else 2
    mode = _mode(layout['mode'])
    grouped = mode == 'grouped_pavilions'
    subject = layout['plan']
    _keys(subject, ('form', 'width', 'depth', 'seed'), 'plan')
    if subject['form'] != 'corner_house':
        raise ValueError('composition: the turret composition requires corner_house')
    for name in ('width', 'depth'):
        _integer(subject[name], 'plan.' + name, 1)
    _integer(subject['seed'], 'plan.seed')
    _keys(layout['rhythm'], ('pattern', 'phase'), 'rhythm')
    rhythm, phase = _rhythm(layout['rhythm']['pattern'], layout['rhythm']['phase'])
    _keys(layout['wings'], WINGS, 'wings')
    corner = layout['corner']
    _keys(corner, ('family', 'projection', 'origin_margin', 'finial', 'visual_rank'), 'corner')
    for name in ('projection', 'origin_margin', 'visual_rank'):
        _integer(corner[name], 'corner.' + name, 0)
    expected_corner = {'family': 'turret', 'projection': int(grouped),
                       'origin_margin': relief if grouped else 0, 'finial': grouped, 'visual_rank': 1}
    if type(corner['finial']) is not bool or dict(corner) != expected_corner:
        raise ValueError('composition: corner must follow the selected projection and finial mode')
    strategy = 'source_plants_by_group' if grouped else 'legacy_source_plants'
    if layout['color_strategy'] != strategy:
        raise ValueError('composition: color_strategy must use sourced plants only')
    if layout['limitations'] != ['shutter_color_variants_unavailable']:
        raise ValueError('composition: unsupported shutter colors must remain declared unavailable')

    for wing_name in WINGS:
        wing = layout['wings'][wing_name]
        label = 'wings.' + wing_name
        _keys(wing, ('bay_count', 'focal_bay', 'groups', 'bays', 'pier_boundaries',
                     'extra_pitch_total', 'extra_width', 'chimney_policy', 'chimney_anchors'), label)
        count = _integer(wing['bay_count'], label + '.bay_count', 5 if wing_name == 'north' else 4)
        for name in ('groups', 'bays', 'pier_boundaries', 'chimney_anchors'):
            if not isinstance(wing[name], list):
                raise ValueError('composition: %s.%s must be a list' % (label, name))
        if len(wing['bays']) != count:
            raise ValueError('composition: %s must declare each bay once' % label)
        groups = wing['groups']
        expected_roles = list(_GROUP_ROLES) if grouped else ['flat']
        if len(groups) != len(expected_roles):
            raise ValueError('composition: %s has an invalid group hierarchy' % label)
        covered, group_lookup = [], {}
        for group, role in zip(groups, expected_roles):
            _keys(group, ('id', 'role', 'bays'), label + '.group')
            if not isinstance(group['id'], str) or not group['id'] or group['id'] in group_lookup:
                raise ValueError('composition: group ids must be nonempty and unique per wing')
            indices = group['bays']
            if group['role'] != role or not isinstance(indices, list) or not indices:
                raise ValueError('composition: %s requires all ordered groups, including recesses' % label)
            for index in indices:
                _integer(index, label + '.group bay', 0)
            if indices != list(range(indices[0], indices[0] + len(indices))):
                raise ValueError('composition: group bays must be contiguous')
            if role in ('central_pavilion', 'end_pavilion') and len(indices) != 1:
                raise ValueError('composition: each pavilion must occupy exactly one bay')
            covered.extend(indices)
            group_lookup[group['id']] = group
        if covered != list(range(count)):
            raise ValueError('composition: groups must cover ordered bays once without gaps')
        focal = wing['focal_bay']
        if grouped:
            _integer(focal, label + '.focal_bay', 1)
            if focal != groups[1]['bays'][0] or focal > count - 3:
                raise ValueError('composition: focal bay must leave a recessed bay before the terminal pavilion')
        elif focal is not None:
            raise ValueError('composition: flat baseline must not introduce a focal bay')
        for index, bay in enumerate(wing['bays']):
            _keys(bay, ('index', 'group', 'role', 'projection', 'dormer_grade',
                        'window_grade', 'plant_accent'), label + '.bay')
            _integer(bay['index'], label + '.bay.index', 0)
            _integer(bay['projection'], label + '.bay.projection', 0)
            if (bay['index'] != index or not isinstance(bay['group'], str)
                    or bay['group'] not in group_lookup):
                raise ValueError('composition: each bay must have its ordered index and a known group')
            group = group_lookup[bay['group']]
            if index not in group['bays']:
                raise ValueError('composition: bay group disagrees with group coverage')
            pavilion = group['role'] in ('central_pavilion', 'end_pavilion')
            role = 'corner_transition' if index == 0 else (group['role'] if pavilion else 'recessed')
            roof_grade = 'none' if index == 0 else ('pavilion' if pavilion else 'ordinary')
            if bay['role'] != role or bay['projection'] != (relief if pavilion else 0):
                raise ValueError('composition: bay role and projection must follow its group')
            if bay['dormer_grade'] != roof_grade:
                raise ValueError('composition: dormer grade must echo the facade pavilion hierarchy')
            if bay['window_grade'] != ('emphasized' if pavilion else 'standard'):
                raise ValueError('composition: window emphasis must follow the pavilion hierarchy')
            if type(bay['plant_accent']) is not bool or bay['plant_accent'] != pavilion:
                raise ValueError('composition: plant accents must follow pavilion bays')

        expected_boundaries = [{'after_bay': group['bays'][-1], 'width': 2,
                                'extra_pitch': 6 - rhythm[(phase + group['bays'][-1]) % len(rhythm)]}
                               for group in groups[:-1]]
        for boundary in wing['pier_boundaries']:
            _keys(boundary, ('after_bay', 'width', 'extra_pitch'), label + '.pier_boundary')
            for name in ('after_bay', 'width', 'extra_pitch'):
                _integer(boundary[name], label + '.pier_boundary.' + name, 0)
        if wing['pier_boundaries'] != expected_boundaries:
            raise ValueError('composition: widened piers must coincide with every group boundary')
        extra = sum(row['extra_pitch'] for row in expected_boundaries)
        _integer(wing['extra_pitch_total'], label + '.extra_pitch_total', 0)
        _integer(wing['extra_width'], label + '.extra_width', 0)
        if wing['extra_pitch_total'] != extra or wing['extra_width'] != extra + corner['origin_margin']:
            raise ValueError('composition: declared width reserve disagrees with piers and corner margin')
        policy = 'focal_clusters' if grouped else 'legacy_fixed'
        if wing['chimney_policy'] != policy:
            raise ValueError('composition: chimney policy must follow the selected mode')
        anchors = wing['chimney_anchors']
        expected_anchor_roles = ['central_pavilion', 'end_pavilion'] if grouped else []
        if len(anchors) != len(expected_anchor_roles):
            raise ValueError('composition: chimneys must form a cluster at each pavilion focus')
        for anchor, role in zip(anchors, expected_anchor_roles):
            _keys(anchor, ('bay', 'target_flues', 'group_role'), label + '.chimney_anchor')
            _integer(anchor['bay'], label + '.chimney_anchor.bay', 0)
            _integer(anchor['target_flues'], label + '.chimney_anchor.target_flues', 4)
            if anchor['target_flues'] > 6:
                raise ValueError('composition: chimney clusters target four to six flues')
            expected_bay = focal if role == 'central_pavilion' else count - 1
            if anchor['group_role'] != role or anchor['bay'] != expected_bay:
                raise ValueError('composition: chimney anchor must coincide with its pavilion focus')
