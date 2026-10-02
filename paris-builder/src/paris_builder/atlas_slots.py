"""Decide before assembly, not after.

The project's repair loop built voxels, rendered them, looked at the pictures, then
rewrote generator *code*, and did that 27 times on one building with no net progress.
Two things made convergence impossible: the step was a whole-code rewrite, so the design
had no identity to hill-climb on, and the defect was discovered as pixels, which is the
most expensive and noisiest place to discover it.

The atlas line changed the shape of the problem without anyone using the change. A
building is now a composition spec of about thirty lines expanded deterministically from
a library of 92 hand-made, hash-verified pieces. So the loop can move onto the spec:
resolve every slot, check every rule, and only then assemble once.

`resolve()` walks the *identical* assembly path with writes disabled, so the slot plan it
returns is the one the real build would produce - a separate planner would drift from the
builder, and two disagreeing descriptions of one geometry is the failure this project
keeps paying for. `validate_slots()` then applies the predicates that are decidable from
that plan: every slot has a piece, every piece fits where it was put, nothing falls
outside the scene, the required element families are all present, and bands tile their
segment without a gap.
"""
import json
from pathlib import Path

from . import atlas_rules as rules

ROOT = Path(__file__).resolve().parents[2]

#: Element families a Haussmann corner apartment cannot be missing, mapped to the role
#: prefixes the assembly driver actually emits. The prefixes are taken from a real dry
#: run's role list, not guessed: window bays are `bay-noble-*` / `bay-standard-*` and the
#: corner is `turret-*`, so a guessed prefix would report a present family as missing.
REQUIRED_ROLES = {
    'base': ('base-arcade', 'base'),
    'window_bay': ('bay-noble', 'bay-standard', 'window'),
    'balcony_lower': ('balcony-lower',),
    'balcony_upper': ('balcony-upper',),
    'cornice': ('cornice',),
    'roof': ('roof-',),
    'dormer': ('dormer',),
    'chimney': ('chimney',),
    'corner': ('turret', 'corner'),
}


def resolve(composition, run_dir, bays_north=None, bays_west=None, **kwargs):
    """Dry-run the assembly and return the slot plan without writing a voxel."""
    from .atlas_street1_composed import build_composed
    seed = composition['plan']['seed']
    bays_north = bays_north if bays_north is not None else composition['wings']['north']['bay_count']
    bays_west = bays_west if bays_west is not None else composition['wings']['west']['bay_count']
    scene, plan = build_composed(run_dir, seed, bays_north, bays_west, composition,
                                 dry_run=True, **kwargs)
    return plan


def _roles(stamps):
    out = {}
    for row in stamps:
        out.setdefault(row['role'], []).append(row)
    return out


def check_slots_resolved(stamps):
    """Every stamp must actually place cells; a zero means the slot chose a dead piece."""
    empty = [{'id': row['id'], 'role': row['role'], 'anchor': row['anchor']}
             for row in stamps if not row.get('placed')]
    return {'rule': 'slots_resolved', 'kind': 'spec',
            'status': 'FAIL' if empty else ('PASS' if stamps else 'UNMEASURED'),
            'measured': {'stamps': len(stamps), 'empty': len(empty)},
            'detail': ('%d slot(s) resolved to a piece that placed nothing' % len(empty))
                      if empty else '%d slots each placed at least one cell' % len(stamps),
            'failures': empty[:12]}


def check_scene_fit(stamps):
    """A piece falling outside the scene means the slot arithmetic and the scene disagree."""
    bad = [{'id': row['id'], 'role': row['role'], 'anchor': row['anchor'],
            'scene_clipped': row.get('scene_clipped', 0), 'size_whd': row.get('size_whd')}
           for row in stamps if row.get('scene_clipped')]
    return {'rule': 'scene_fit', 'kind': 'spec',
            'status': 'FAIL' if bad else ('PASS' if stamps else 'UNMEASURED'),
            'measured': {'clipped_stamps': len(bad)},
            'detail': ('%d stamp(s) extend past the scene bounds' % len(bad)) if bad
                      else 'every stamp lies inside the scene',
            'failures': bad[:12]}


def check_required_families(stamps, required=None):
    """A named element family with no slot at all is a spec omission, not a detail gap."""
    required = required or REQUIRED_ROLES
    roles = _roles(stamps)
    missing = []
    for family, prefixes in required.items():
        if not any(any(role.startswith(prefix) for prefix in prefixes) for role in roles):
            missing.append(family)
    return {'rule': 'required_families', 'kind': 'spec',
            'status': 'FAIL' if missing else ('PASS' if stamps else 'UNMEASURED'),
            'measured': {'present': sorted(roles), 'missing': missing},
            'detail': ('missing element families: ' + ', '.join(missing)) if missing
                      else 'all required element families have slots',
            'failures': missing}


def check_piece_fits(stamps):
    """A piece taller than the storey band it sits in cannot be what the spec intended."""
    suspects = []
    for row in stamps:
        size = row.get('size_whd') or []
        role = str(row.get('role') or '')
        height = size[1] if len(size) > 1 else None
        if height is None:
            continue
        # Roof, chimney and corner pieces legitimately span several storeys.
        if any(token in role for token in ('roof', 'chimney', 'corner', 'planter', 'turret')):
            continue
        if height > 20:
            suspects.append({'id': row['id'], 'role': role, 'size_whd': size,
                             'anchor': row['anchor']})
    return {'rule': 'piece_fits_storey', 'kind': 'spec',
            'status': 'FAIL' if suspects else ('PASS' if stamps else 'UNMEASURED'),
            'measured': {'suspects': len(suspects)},
            'detail': ('%d facade piece(s) taller than any storey band' % len(suspects))
                      if suspects else 'facade pieces fit their storey bands',
            'failures': suspects[:12]}


def check_band_continuity(stamps):
    """Bands tile a segment; a gap between two tiles of one band is a visible seam."""
    by_role = {}
    for row in stamps:
        role = str(row.get('role') or '')
        if not any(token in role for token in ('roof-', 'cornice', 'balcony', 'base-arcade')):
            continue
        by_role.setdefault(role, []).append(row)
    gaps = []
    for role, rows in by_role.items():
        if len(rows) < 2:
            continue
        # Tiles of one band share the coordinate across the band; the band then runs
        # ALONG the other axis. Getting this backwards made a three-cell gap read as a
        # pass, which is exactly the kind of silent miss this check exists to prevent.
        same_x = all(row['anchor'][0] == rows[0]['anchor'][0] for row in rows)
        axis = 2 if same_x else 0
        ordered = sorted(rows, key=lambda row: row['anchor'][axis])
        for before, after in zip(ordered, ordered[1:]):
            width = before['size_whd'][axis]
            end = before['anchor'][axis] + width
            if after['anchor'][axis] > end:
                gaps.append({'role': role, 'axis': 'xz'[axis // 2],
                             'gap': after['anchor'][axis] - end,
                             'from': before['anchor'], 'to': after['anchor']})
    return {'rule': 'band_continuity', 'kind': 'spec',
            'status': 'FAIL' if gaps else ('PASS' if by_role else 'UNMEASURED'),
            'measured': {'bands': sorted(by_role), 'gaps': len(gaps)},
            'detail': ('%d gap(s) between tiles of the same band' % len(gaps)) if gaps
                      else 'every band tiles its segment without a gap',
            'failures': gaps[:12]}


SLOT_CHECKS = (check_slots_resolved, check_scene_fit, check_required_families,
               check_piece_fits, check_band_continuity)


def validate_slots(plan, style=None):
    """Run every slot-plan predicate and the spec-side style rules over one dry run."""
    stamps = plan.get('stamps') or []
    results = [check(stamps) for check in SLOT_CHECKS]
    frame_spec = plan.get('frame_spec') or {}
    if style is not None:
        results += rules.spec_checks(style, plan.get('composition') or {}, frame_spec)
    return results


def report(plan, results):
    """One JSON-serializable record a gate and a repair prompt can both read."""
    summary = {'PASS': 0, 'FAIL': 0, 'UNMEASURED': 0}
    for row in results:
        summary[row['status']] = summary.get(row['status'], 0) + 1
    failed = [row for row in results if row['status'] == 'FAIL']
    return {
        'status': 'FAIL' if failed else ('PASS' if summary['PASS'] else 'UNMEASURED'),
        'counts': summary,
        'failed_rules': [row['rule'] for row in failed],
        'unmeasured_rules': [row['rule'] for row in results if row['status'] == 'UNMEASURED'],
        'results': results,
        'plan': {
            'run': plan.get('run'), 'seed': plan.get('seed'),
            'scene': plan.get('scene'), 'stamps': len(plan.get('stamps') or []),
            'derived_pieces': len(plan.get('derived_pieces') or {}),
            'fill': plan.get('fill'),
        },
        'note': 'Decided before assembly. A FAIL here is a spec defect, fixable by editing '
                'the composition or the frame spec, not by rewriting generator code.',
    }


def write_report(path, plan, results):
    payload = report(plan, results)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    return payload
