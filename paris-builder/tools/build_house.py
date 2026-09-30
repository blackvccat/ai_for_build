"""Build one house design from the three layers, validate it, and render it.

This is the design pipeline: it takes a brief, runs the facade competition the brief
requires, refines the chosen scheme in three tiers, validates the result the way the
project validates every artifact (file, geometry, states, byte reproducibility), and
renders the seven views plus two orbit rings.

Nothing here is used by the recorded PAR-002 delivery, so that package keeps reproducing
byte for byte.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from paris_builder import design, facade, house, technique  # noqa: E402
from paris_builder.exporter import dump_json, write_schematic  # noqa: E402
from paris_builder.geometry import inspect_geometry  # noqa: E402
from paris_builder.preview3d import render_previews  # noqa: E402
from paris_builder.schematic import load_schematic  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BRIEF = ROOT / 'knowledge/workflow/house-001.brief.json'

#: The three refinement tiers the brief requires. Tier 1 is massing and openings, tier 2
#: adds the framing of every opening and the storey lines, tier 3 adds the surface
#: dressing and the roof furniture. Each tier is rendered so the review can see what the
#: tier actually added.
TIERS = {
    1: {'name': 'massing', 'techniques': ('window_surround', 'cornice'),
        'note': '体量、开口、檐口：只有骨架和洞口'},
    2: {'name': 'framing', 'techniques': ('window_surround', 'cornice', 'string_course',
                                          'door_leaf', 'shopfront'),
        'note': '加窗套、层线、门、店面：立面开始读得出来'},
    3: {'name': 'dressing', 'techniques': ('window_surround', 'cornice', 'string_course',
                                           'door_leaf', 'shopfront', 'guard_rail',
                                           'rustication', 'cresting', 'quoins', 'pilaster'),
        'note': '加铁栏、粗石基座、转角石、壁柱、脊饰：完整交付'},
}


def brief_load() -> dict:
    return json.loads(BRIEF.read_text(encoding='utf-8'))


def candidate_plans(brief: dict, seed: int, forms=None) -> list:
    """The candidates a competition runs on: one form, three facade schemes."""
    forms = forms or ['street_row', 'apartment_block', 'court_palace']
    plans = []
    for index, form in enumerate(forms):
        plan = design.plan_for(form, seed=seed + index * 101, scheme=None,
                               storeys=brief['scale']['storeys'])
        plans.append(plan)
    return plans


#: The brief requires three facade schemes to compete. These three are the honest
#: shortlist for a Parisian apartment building: the Haussmann street front, the plainer
#: terrace of the same period, and a palace-style front. `civic_colonnade` is for public
#: buildings and `shop_terrace` is a subset of the Haussmann ground floor, so neither is
#: a real alternative for this brief.
COMPETING_SCHEMES = ('haussmann_apartment', 'plain_terrace', 'palace_front')


def facade_competition(brief: dict, seed: int, form: str, schemes=None) -> dict:
    """Build the same form with each competing facade scheme and score each one.

    The scores are measurements, not opinions: how much of the street plane is glazing,
    how regular the bay rhythm is, whether the ground floor actually carries the shops
    and the entrance, and how much of the elevation the scheme dresses.
    """
    schemes = schemes or list(COMPETING_SCHEMES)
    entries = []
    for name in schemes:
        plan = design.plan_for(form, seed=seed, scheme=name,
                               storeys=brief['scale']['storeys'])
        scene, manifest = design.build(plan)
        street = next((w for w in manifest['walls'] if w['role'] == 'primary'), None)
        # Glazing share is measured on the plane the street sees, per parcel height.
        glazing, cells = 0, 0
        structure, _ctx = house.build(plan.form, plan.width, plan.depth, plan.storeys, plan.seed)
        palette, volume = scene.palette, scene.volume
        for wall in structure.walls:
            if wall.role != 'primary':
                continue
            for u in range(wall.length):
                for y in range(1, wall.height + 1):
                    x, _yy, z = wall.point(u, y, 0)
                    name_at = palette[int(volume[y, z, x])]
                    cells += 1
                    if name_at.startswith('minecraft:white_stained_glass'):
                        glazing += 1
        share = glazing / cells if cells else 0.0
        kinds = street['by_kind'] if street else {}
        rhythm = street['pier_widths'] if street else []
        # A regular rhythm is one where the piers are all the same width.
        regular = 1.0 if len(set(rhythm)) <= 1 else 1.0 / len(set(rhythm))
        ground_ok = 1.0 if (kinds.get('shop', 0) + kinds.get('door', 0)) else 0.0
        dressed = len(manifest['techniques']) / float(len(technique.TECHNIQUES))
        score = round(100 * (0.35 * min(1.0, share / 0.20) + 0.25 * regular
                             + 0.20 * ground_ok + 0.20 * dressed), 1)
        entries.append({'scheme': name, 'glazing_share': round(share, 4),
                        'bay_groups': street['bay_groups'] if street else 0,
                        'pier_widths': rhythm, 'ground_kinds': kinds,
                        'techniques': sorted(manifest['techniques']),
                        'score': score, 'cells': manifest['cells']})
    entries.sort(key=lambda e: (-e['score'], e['scheme']))
    return {'form': form, 'entries': entries, 'selected': entries[0]['scheme'],
            'criteria': {'glazing_share': 0.35, 'regular_piers': 0.25,
                         'ground_floor': 0.20, 'dressed_elements': 0.20}}


def build_tier(plan, tier: int, out: Path, size: int, render: bool) -> dict:
    """Build one tier, export it, validate it, and optionally render it."""
    scene, manifest = design.build(plan, tier=tier)
    stem = 'tier-%d' % tier
    schematic = out / ('%s.schem' % stem)
    write_schematic(schematic, scene.volume, scene.palette,
                    name='HOUSE-001 %s' % TIERS[tier]['name'])
    read = load_schematic(schematic)
    validation = read.validation()
    geometry = inspect_geometry(read)
    # Byte reproducibility: rebuild from the same recorded plan and compare digests.
    scene2, _manifest2 = design.build(plan, tier=tier)
    rebuild = out / ('%s.rebuild.schem' % stem)
    write_schematic(rebuild, scene2.volume, scene2.palette,
                    name='HOUSE-001 %s' % TIERS[tier]['name'])
    identical = hashlib.sha256(schematic.read_bytes()).hexdigest() == \
        hashlib.sha256(rebuild.read_bytes()).hexdigest()
    rebuild.unlink()
    report = {
        'tier': tier, 'name': TIERS[tier]['name'], 'note': TIERS[tier]['note'],
        'expected_techniques': list(TIERS[tier]['techniques']),
        'plan': plan.describe(),
        'dimensions_whl': [read.width, read.height, read.length],
        'cells': manifest['cells'], 'openings': sum(w['openings'] for w in manifest['walls']),
        'techniques': manifest['techniques'],
        'techniques_by_wall': manifest['techniques_by_wall'],
        'walls': manifest['walls'],
        'file_validation': validation['status'], 'geometry': geometry['status'],
        'repeat_byte_identical': identical,
        'sha256': hashlib.sha256(schematic.read_bytes()).hexdigest(),
    }
    if render:
        previews = render_previews(schematic, out / ('%s-previews' % stem), max_size=size,
                                   orbit=(tier == 3))
        report['previews'] = previews
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', default='HOUSE-001-v0.1')
    parser.add_argument('--seed', type=int, default=7101)
    parser.add_argument('--form', default=None,
                        help='skip the form question and use this form')
    parser.add_argument('--scheme', default=None,
                        help='skip the facade competition and use this scheme')
    parser.add_argument('--width', type=int, default=None)
    parser.add_argument('--depth', type=int, default=None)
    parser.add_argument('--storeys', type=int, default=None)
    parser.add_argument('--size', type=int, default=1000)
    parser.add_argument('--tier', type=int, default=None, choices=sorted(TIERS),
                        help='build only this tier')
    parser.add_argument('--no-render', action='store_true')
    args = parser.parse_args()

    brief = brief_load()
    out = ROOT / 'runs' / args.run
    out.mkdir(parents=True, exist_ok=True)
    dump_json(out / 'brief.json', brief)

    storeys = args.storeys or brief['scale']['storeys']
    # --- form competition: which structure answers the brief at all
    form_scores = []
    for form in sorted(house.FORMS):
        plan = design.plan_for(form, seed=args.seed, storeys=storeys)
        _scene, manifest = design.build(plan)
        street = next((w for w in manifest['walls'] if w['role'] == 'primary'), None)
        form_scores.append({
            'form': form, 'width': plan.width, 'depth': plan.depth,
            'street_walls': sum(1 for w in manifest['walls'] if w['role'] == 'primary'),
            'street_openings': street['openings'] if street else 0,
            'cells': manifest['cells'], 'notes': manifest['structure']['notes'],
        })
    dump_json(out / 'form_survey.json', form_scores)

    form = args.form or 'apartment_block'
    competition = facade_competition(brief, args.seed, form)
    dump_json(out / 'facade_competition.json', competition)
    scheme = args.scheme or competition['selected']

    plan = design.plan_for(form, seed=args.seed, scheme=scheme, width=args.width,
                           depth=args.depth, storeys=storeys)
    dump_json(out / 'design_seeds.json', {
        'seed': args.seed, 'form': form, 'scheme': scheme, 'plan': plan.describe(),
        'note': 'the whole design reproduces from these values',
    })

    tiers = [args.tier] if args.tier else sorted(TIERS)
    reports = []
    for tier in tiers:
        reports.append(build_tier(plan, tier, out, args.size, not args.no_render))
        print('tier %d: %s' % (tier, reports[-1]['techniques']))
    dump_json(out / 'tier_reports.json', reports)

    final = reports[-1]
    gates = {'file_validation': final['file_validation'], 'geometry': final['geometry'],
             'repeat_byte_identical': 'PASS' if final['repeat_byte_identical'] else 'FAIL'}
    summary = {
        'status': 'PASS' if all(v == 'PASS' for v in gates.values()) else 'FAIL',
        **gates,
        'run': args.run, 'form': form, 'scheme': scheme,
        'facade_competition': {e['scheme']: e['score'] for e in competition['entries']},
        'selected_scheme': competition['selected'],
        'dimensions_whl': final['dimensions_whl'], 'cells': final['cells'],
        'openings': final['openings'], 'techniques': final['techniques'],
        'game_acceptance': 'PENDING',
        'note': 'Building designed by the three-layer system (structure/facade/technique). '
                'This is not a game paste test and not user acceptance.',
    }
    dump_json(out / 'design_report.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
