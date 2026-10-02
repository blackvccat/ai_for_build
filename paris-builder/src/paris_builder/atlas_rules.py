"""The style's declared rules, as code.

`knowledge/styles/paris_haussmann_v0.2.json` already states nine machine-checkable
rules in a `frame_check` field, each anchored to a real-evidence note and a Minecraft
evidence note. Until now nothing executed them: the vision reviewer was asked to judge
"does this read as Haussmann" in prose while the project's own numeric invariants sat
unread in a JSON file.

This module runs them. It deliberately does NOT invent thresholds - every bound comes
from the style file, and a rule whose bound is missing reports UNMEASURED instead of
being guessed. That distinction is the whole point: a fabricated rule is worse than no
rule, because it manufactures evidence for a decision nobody made.

Two kinds of rule, and the split matters for one-shot generation:

* SPEC rules read the composition / frame spec only. They run before assembly, in the
  dry run, and can be fixed by editing the spec.
* EXPORT rules read the built schematic. They confirm the spec was realised.
"""
import json
from pathlib import Path

import numpy as np

from . import atlas_geometry as geo

ROOT = Path(__file__).resolve().parents[2]
STYLE_PATH = ROOT / 'knowledge/styles/paris_haussmann_v0.2.json'

#: Rule name -> how it is evaluated. Kept explicit so an unimplemented rule is visible.
RULE_KINDS = {
    'roof_share': 'export', 'cornice_ratio': 'export', 'base_treatment': 'export',
    'vertical_system': 'export', 'bay_rhythm': 'spec', 'composition_hierarchy': 'spec',
    'corner_family': 'spec', 'balcony_levels': 'spec', 'party_walls': 'spec',
}


def load_style(path=None):
    """Read the declared style rules, and record where they came from."""
    target = Path(path) if path else STYLE_PATH
    data = json.loads(target.read_text(encoding='utf-8'))
    data['_source'] = str(target.relative_to(ROOT)) if target.is_relative_to(ROOT) else str(target)
    return data


def _range_from(text):
    """Pull the first `[lo, hi]` or `lo..hi` numeric bound out of a frame_check string."""
    import re
    match = re.search(r'\[\s*([0-9.]+)\s*,\s*([0-9.]+)\s*\]', text or '')
    if match:
        return float(match.group(1)), float(match.group(2))
    match = re.search(r'([0-9.]+)\s*[~-]\s*([0-9.]+)\s*%', text or '')
    if match:
        return float(match.group(1)) / 100.0, float(match.group(2)) / 100.0
    return None


def _result(name, rule, status, measured, expected, detail, kind=None):
    return {'rule': name, 'kind': kind or RULE_KINDS.get(name, 'spec'), 'status': status,
            'measured': measured, 'expected': expected, 'detail': detail,
            'declared_rule': rule.get('rule'), 'frame_check': rule.get('frame_check'),
            'declared_evidence': rule.get('mc_evidence')}


def check_roof_share(style, *, total_top_y, roof_datum_y, segments=None):
    rule = style.get('roof_share') or {}
    bounds = _range_from(rule.get('frame_check'))
    if bounds is None or total_top_y is None or roof_datum_y is None:
        return _result('roof_share', rule, 'UNMEASURED', None, bounds,
                       'missing declared bound or missing level')
    share = (total_top_y - roof_datum_y) / float(total_top_y)
    ok = bounds[0] <= share <= bounds[1]
    detail = 'roof %d..%d of total %d = %.3f' % (roof_datum_y, total_top_y, total_top_y, share)
    if segments is not None:
        slopes = [s['rise_per_run'] for s in segments if s.get('rise_per_run') is not None]
        steep = max(slopes) if slopes else None
        shallow = min(slopes) if slopes else None
        two_regime = bool(steep is not None and shallow is not None and steep - shallow >= 0.5)
        detail += '; steep=%.2f shallow=%.2f two_regime=%s' % (steep or 0, shallow or 0, two_regime)
        if not two_regime:
            ok = False
    return _result('roof_share', rule, 'PASS' if ok else 'FAIL', round(share, 4), bounds, detail)


def check_cornice_ratio(style, *, cornice_top_y, total_top_y):
    rule = style.get('cornice_ratio') or {}
    bounds = _range_from(rule.get('frame_check'))
    if bounds is None or cornice_top_y is None or total_top_y is None:
        return _result('cornice_ratio', rule, 'UNMEASURED', None, bounds,
                       'missing declared bound or missing level')
    ratio = cornice_top_y / float(total_top_y)
    ok = bounds[0] <= ratio <= bounds[1]
    return _result('cornice_ratio', rule, 'PASS' if ok else 'FAIL', round(ratio, 4), bounds,
                   'cornice y=%d / total y=%d = %.3f' % (cornice_top_y, total_top_y, ratio))


def check_vertical_system(style, levels, *, noble_window_top=None, standard_window_top=None):
    rule = style.get('vertical_system') or {}
    required = ('arcade_base', 'standard_base', 'noble_base', 'cornice_base', 'roof_datum')
    missing = [name for name in required if levels.get(name) is None]
    if missing:
        return _result('vertical_system', rule, 'UNMEASURED', None, required,
                       'missing declared levels: ' + ', '.join(missing))
    ordered = all(levels[required[i]] < levels[required[i + 1]] for i in range(len(required) - 1))
    detail = 'ordered=%s' % ordered
    ok = ordered
    if noble_window_top is not None and standard_window_top is not None:
        noble_higher = noble_window_top > standard_window_top
        detail += '; noble window top %s > standard %s = %s' % (
            noble_window_top, standard_window_top, noble_higher)
        ok = ok and noble_higher
    return _result('vertical_system', rule, 'PASS' if ok else 'FAIL',
                   {k: levels[k] for k in required}, 'increasing sequence', detail)


def check_bay_rhythm(style, rhythm, *, groups=None):
    rule = style.get('bay_rhythm') or {}
    pattern = list(rhythm or [])
    if len(pattern) < 2:
        return _result('bay_rhythm', rule, 'UNMEASURED', pattern, '|delta| <= 1',
                       'rhythm pattern too short')
    deltas = [abs(pattern[i + 1] - pattern[i]) for i in range(len(pattern) - 1)]
    deltas.append(abs(pattern[0] - pattern[-1]))
    ok = max(deltas) <= 1
    detail = 'pattern=%s deltas=%s' % (pattern, deltas)
    if groups:
        projections = sorted({row.get('projection', 0) for wing in groups.values()
                              for row in (wing.get('groups') or [])})
        detail += '; group projections=%s' % projections
    return _result('bay_rhythm', rule, 'PASS' if ok else 'FAIL', deltas, '<=1', detail)


def check_composition_hierarchy(style, wings, corner):
    """At least one of: a projecting group, a corner emphasis, a roof rhythm break."""
    rule = style.get('composition_hierarchy') or {}
    if not wings:
        return _result('composition_hierarchy', rule, 'UNMEASURED', None,
                       'pavilion | corner | roof break', 'no wings declared')
    projecting, flat_wings = [], []
    for name, wing in wings.items():
        rows = wing.get('groups') or []
        projections = [row.get('projection', 0) for row in rows]
        if any(value > 0 for value in projections):
            projecting.append({'wing': name, 'projections': projections,
                               'roles': [row.get('role') for row in rows]})
        else:
            flat_wings.append(name)
    corner_projection = int((corner or {}).get('projection', 0) or 0)
    ok = bool(projecting) or corner_projection > 0
    return _result('composition_hierarchy', rule, 'PASS' if ok else 'FAIL',
                   {'projecting_wings': projecting, 'flat_wings': flat_wings,
                    'corner_projection': corner_projection},
                   'at least one pavilion or corner emphasis',
                   'homogeneous facades fail this rule')


#: The frame builder names a corner pavilion `turret`; the style vocabulary names it
#: `pavilion` (角亭). Same design intent, two spellings - normalise rather than fail.
CORNER_ALIASES = {'turret': 'pavilion', 'rotonde': 'rounded', 'pan_coupe': 'chamfer',
                  'chamfered': 'chamfer', 'curved': 'rounded'}


def check_corner_family(style, corner, justification=None):
    rule = style.get('corner_family') or {}
    allowed = {'chamfer', 'rounded', 'prow', 'pavilion', 'recessed_court'}
    declared = (corner or {}).get('family')
    if not declared:
        return _result('corner_family', rule, 'UNMEASURED', None, sorted(allowed),
                       'no corner family declared')
    family = CORNER_ALIASES.get(str(declared), str(declared))
    if family not in allowed:
        return _result('corner_family', rule, 'FAIL',
                       {'declared': declared, 'normalised': family}, sorted(allowed),
                       'corner family outside the declared vocabulary')
    # pan coupé and rounded are the apartment default; anything else needs a reason.
    if family in ('chamfer', 'rounded'):
        return _result('corner_family', rule, 'PASS', {'declared': declared, 'family': family},
                       'apartment default', 'no justification needed')
    if not justification:
        return _result('corner_family', rule, 'FAIL',
                       {'declared': declared, 'family': family}, 'justification required',
                       'non-default corner family (%s) requires an explicit justification'
                       % family)
    return _result('corner_family', rule, 'PASS',
                   {'declared': declared, 'family': family}, 'justification required',
                   'justified: ' + str(justification)[:160])


def check_base_treatment(style, *, base_top_y, total_top_y, base_materials, body_materials):
    rule = style.get('base_treatment') or {}
    bounds = _range_from(rule.get('frame_check'))
    if bounds is None or base_top_y is None or total_top_y is None:
        return _result('base_treatment', rule, 'UNMEASURED', None, bounds or '0.12..0.20',
                       'missing declared bound or missing level')
    share = base_top_y / float(total_top_y)
    differs = bool(base_materials) and bool(body_materials) and not (base_materials & body_materials)
    ok = bounds[0] <= share <= bounds[1] and differs
    return _result('base_treatment', rule, 'PASS' if ok else 'FAIL',
                   {'share': round(share, 4), 'material_differs': differs},
                   bounds, 'base y<=%d / total %d; base materials must differ from body'
                   % (base_top_y, total_top_y))


def check_balcony_levels(style, baselines, levels):
    """Exactly two continuous bands - one at the noble floor, one below the cornice.

    `balcony_baselines` is emitted per wing AND per group, so a three-group wing yields
    six rows for the two bands it is allowed. The rule is about roles, not row count:
    every row must carry one of exactly two roles, each role must sit at a single height
    (a continuous band, not scattered baselines), and those heights must align to
    `noble_base` and to just under `cornice_base`.
    """
    rule = style.get('balcony_levels') or {}
    rows = baselines or []
    if not rows:
        return _result('balcony_levels', rule, 'UNMEASURED', None, 'two roles: lower, upper',
                       'no balcony baselines declared')
    by_role = {}
    for row in rows:
        if isinstance(row, dict):
            by_role.setdefault(str(row.get('role') or 'unknown'), []).append(row.get('y'))
        else:
            by_role.setdefault('unknown', []).append(row)
    if set(by_role) != {'lower', 'upper'}:
        return _result('balcony_levels', rule, 'FAIL', sorted(by_role), ['lower', 'upper'],
                       'balcony bands must be exactly two: a noble-floor band and an upper band')
    expected = {'lower': levels.get('noble_base'), 'upper': levels.get('cornice_base')}
    detail, ok = {}, True
    for role, values in by_role.items():
        heights = sorted({int(v) for v in values if v is not None})
        aligned = [h for h in heights
                   if expected[role] is not None and abs(h - int(expected[role])) <= 2]
        detail[role] = {'heights': heights, 'expected': expected[role],
                        'aligned': bool(aligned) and len(heights) == 1}
        ok = ok and detail[role]['aligned']
    return _result('balcony_levels', rule, 'PASS' if ok else 'FAIL', detail,
                   {'noble_base': expected['lower'], 'cornice_base': expected['upper']},
                   'each band must be one continuous height aligned to its declared level')


def _face_entries(value):
    """Accept a face-name->declaration mapping or a list of declaration objects.

    `party_faces` is written as a list of objects carrying `face` and
    `glazing_allowed`, so a naive `str(row)` conversion would discard the very field
    this rule exists to check.
    """
    if not value:
        return []
    if isinstance(value, dict):
        return [(name, row) for name, row in value.items()]
    out = []
    for row in value:
        if isinstance(row, dict):
            name = row.get('face') or row.get('name') or str(row.get('coordinate', '?'))
            out.append((str(name), row))
        else:
            out.append((str(row), None))
    return out


def check_party_walls(style, party_faces, street_faces):
    rule = style.get('party_walls') or {}
    parties = _face_entries(party_faces)
    streets = _face_entries(street_faces)
    if not parties and not streets:
        return _result('party_walls', rule, 'UNMEASURED', None,
                       'party glazing_allowed=false; street true', 'no faces declared')
    bad, undeclared = [], []
    for name, value in parties:
        allowed = value.get('glazing_allowed') if isinstance(value, dict) else None
        if allowed is not False:
            (bad if allowed is not None else undeclared).append(
                {'face': name, 'glazing_allowed': allowed})
    for name, value in streets:
        allowed = value.get('glazing_allowed') if isinstance(value, dict) else None
        if allowed is not True:
            (bad if allowed is not None else undeclared).append(
                {'face': name, 'glazing_allowed': allowed})
    # The declaration must be explicit: a bare face list does not state glazing policy.
    status = 'FAIL' if bad else ('UNMEASURED' if undeclared else 'PASS')
    return _result('party_walls', rule, status, {'violations': bad, 'undeclared': undeclared},
                   'every face must declare glazing_allowed explicitly',
                   'party faces false, street faces true; %d undeclared, %d wrong'
                   % (len(undeclared), len(bad)))


#: Which frame_spec level feeds each check.
LEVEL_KEYS = ('arcade_base', 'standard_base', 'noble_base', 'lower_balcony_platform',
              'cornice_base', 'body_top_y', 'roof_datum', 'dormer_lower_base',
              'dormer_upper_base', 'primary_roof_top_y', 'corner_control_top_y',
              'turret_shaft_base', 'turret_cap_base')


def spec_checks(style, composition, frame_spec):
    """Every rule that can be decided from the design contract, before any block is written."""
    wings = composition.get('wings') or {}
    corner = composition.get('corner') or {}
    corner_spec = (frame_spec or {}).get('corner') or {}
    merged_corner = {**corner, **{k: v for k, v in corner_spec.items()
                                  if k in ('family', 'projection')}}
    results = [
        check_bay_rhythm(style, (composition.get('rhythm') or {}).get('pattern'), groups=wings),
        check_composition_hierarchy(style, wings, merged_corner),
        check_corner_family(style, merged_corner, (frame_spec or {}).get('corner_justification')),
        check_balcony_levels(style, (frame_spec or {}).get('balcony_baselines'),
                             (frame_spec or {}).get('fixed_levels') or {}),
        check_party_walls(style, (frame_spec or {}).get('party_faces'),
                          (frame_spec or {}).get('street_faces')),
    ]
    return results


def export_checks(style, read, frame_spec, *, material_split=None):
    """Every rule that needs the built schematic."""
    levels = (frame_spec or {}).get('fixed_levels') or {}
    report = geo.roof_plane(read)
    results = []
    if report.get('status') != 'MEASURED':
        results.append({'rule': 'roof_share', 'kind': 'export', 'status': 'UNMEASURED',
                        'detail': report.get('reason', 'roof not measurable'),
                        'declared_rule': (style.get('roof_share') or {}).get('rule')})
        results.append({'rule': 'cornice_ratio', 'kind': 'export', 'status': 'UNMEASURED',
                        'detail': report.get('reason', 'roof not measurable'),
                        'declared_rule': (style.get('cornice_ratio') or {}).get('rule')})
    else:
        total_top_y = report['max_raw_top_y']
        # No fallback to a measured datum: the rule is about the roof the design DECLARED,
        # so a spec without `roof_datum` is unmeasurable rather than silently re-based on
        # whatever the geometry happens to do.
        roof_datum_y = levels.get('roof_datum')
        span = (frame_spec or {}).get('north_wing_span')
        limit = (frame_spec or {}).get('wing_depth')
        segments = None
        if span and limit:
            profile = geo.eave_profile(report, 'north', span=tuple(span), limit=limit)
            segments = geo.slope_segments(profile)
        results.append(check_roof_share(style, total_top_y=total_top_y,
                                        roof_datum_y=roof_datum_y, segments=segments))
        results.append(check_cornice_ratio(style, cornice_top_y=levels.get('cornice_base'),
                                           total_top_y=total_top_y))
    results.append(check_vertical_system(style, levels))
    if material_split:
        results.append(check_base_treatment(style, base_top_y=levels.get('standard_base'),
                                            total_top_y=levels.get('primary_roof_top_y'),
                                            base_materials=material_split.get('base') or set(),
                                            body_materials=material_split.get('body') or set()))
    else:
        results.append({'rule': 'base_treatment', 'kind': 'export', 'status': 'UNMEASURED',
                        'detail': 'no material split supplied',
                        'declared_rule': (style.get('base_treatment') or {}).get('rule')})
    return results


def summarize(results):
    """Roll a rule result list into a status a gate can act on."""
    counts = {'PASS': 0, 'FAIL': 0, 'UNMEASURED': 0}
    for row in results:
        counts[row.get('status', 'UNMEASURED')] = counts.get(row.get('status', 'UNMEASURED'), 0) + 1
    return {'status': 'FAIL' if counts['FAIL'] else ('PASS' if counts['PASS'] else 'UNMEASURED'),
            'counts': counts,
            'failed': [row['rule'] for row in results if row.get('status') == 'FAIL'],
            'unmeasured': [row['rule'] for row in results if row.get('status') == 'UNMEASURED']}
