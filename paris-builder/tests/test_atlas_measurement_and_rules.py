# -*- coding: utf-8 -*-
"""Tests for the measurement, rule and slot-plan layers.

These three modules exist so a building can be judged by numbers instead of by prose,
and so the judgement happens before assembly rather than after. The tests therefore aim
at the failure modes that made the old loop unable to converge:

* a measurement that cannot tell a chimney from a roof slope;
* a rule whose threshold was invented rather than read from the style file;
* a dry run that does not actually mirror the real build.
"""
import unittest

import numpy as np

from paris_builder import atlas_geometry as geo
from paris_builder import atlas_rules as rules
from paris_builder import atlas_slots as slots


class StubRead:
    """Minimal stand-in for a loaded schematic: a volume plus an id->state map."""

    def __init__(self, volume, id_to_state):
        self.volume = volume
        self.id_to_state = id_to_state


def simple_building(*, with_chimney=True, roof_rise=8, width=21, depth=21, height=52):
    """A square hip roof on a solid block, optionally with one chimney above the crown.

    Six cells of headroom are reserved above the roof crown so the chimney can stand
    clear of it - otherwise both clamp to the same ceiling and the test would pass for
    the wrong reason.
    """
    volume = np.zeros((height, depth, width), np.int32)
    states = {0: 'minecraft:air', 1: 'minecraft:smooth_sandstone', 2: 'minecraft:deepslate_tiles'}
    wall_top = height - roof_rise - 6
    for y in range(wall_top + 1):
        volume[y, 1:depth - 1, 1:width - 1] = 1
    # Steep lower flank then a flat crown: the plane rises with distance from the eave.
    for z in range(1, depth - 1):
        for x in range(1, width - 1):
            d = min(z - 1, depth - 2 - z, x - 1, width - 2 - x)
            rise = min(d, roof_rise)
            for y in range(wall_top + 1, wall_top + 2 + rise):
                volume[y, z, x] = 2
    if with_chimney:
        top = min(height, wall_top + 2 + roof_rise + 4)
        for y in range(wall_top + 1, top):
            volume[y, depth // 2, width // 2] = 2
    return StubRead(volume, states)


class RoofPlaneTests(unittest.TestCase):
    def test_roof_plane_is_measured_and_reports_its_method(self):
        report = geo.roof_plane(simple_building())
        self.assertEqual(report['status'], 'MEASURED')
        self.assertIn('percentile', report['method'])
        self.assertGreater(report['roof_cells'], 0)

    def test_a_chimney_is_attached_volume_not_a_slope_step(self):
        """The whole reason this module exists: a chimney must not move the roof plane."""
        plain = geo.roof_plane(simple_building(with_chimney=False))
        chimney = geo.roof_plane(simple_building(with_chimney=True))
        # The raw reading is taller with a chimney ...
        self.assertGreater(chimney['max_raw_top_y'], plain['max_raw_top_y'])
        # ... but the measured plane is not, and the difference is reported as attached.
        self.assertEqual(chimney['max_plane_top_y'], plain['max_plane_top_y'])
        self.assertGreater(chimney['attached_cells'], 0)
        self.assertTrue(any(row['max_rise'] > 0 for row in chimney['attached_clusters']))

    def test_unmeasured_material_is_reported_not_guessed(self):
        read = StubRead(np.zeros((5, 5, 5), np.int32), {0: 'minecraft:air', 1: 'minecraft:stone'})
        report = geo.roof_plane(read)
        self.assertEqual(report['status'], 'UNMEASURED')
        self.assertIn('reason', report)

    def test_forty_five_degree_passes_a_shallow_roof_and_fails_a_steep_one(self):
        shallow = {'profile': [{'distance': d, 'plane_y': d // 2} for d in range(12)]}
        steep = {'profile': [{'distance': d, 'plane_y': d * 2} for d in range(12)]}
        self.assertEqual(geo.forty_five_degree(shallow)['status'], 'PASS')
        self.assertEqual(geo.forty_five_degree(steep)['status'], 'FAIL')

    def test_slope_segments_find_the_two_regimes_of_a_mansard(self):
        profile = {'profile': [{'distance': d, 'plane_y': min(d * 2, 8) + max(0, d - 4) // 4}
                               for d in range(20)]}
        segments = geo.slope_segments(profile)
        slopes = [row['rise_per_run'] for row in segments]
        self.assertGreaterEqual(len(segments), 2)
        self.assertGreater(max(slopes), min(slopes))

    def test_eave_profile_needs_a_face_it_knows(self):
        report = geo.roof_plane(simple_building())
        with self.assertRaises(ValueError):
            geo.eave_profile(report, 'sideways')


class RuleTests(unittest.TestCase):
    def setUp(self):
        self.style = rules.load_style()

    def test_every_declared_rule_has_an_implementation(self):
        missing = [name for name in rules.RULE_KINDS if name not in self.style]
        self.assertEqual(missing, [], 'style file lost a rule these checks read')

    def test_bounds_come_from_the_style_file_not_from_code(self):
        """A rule with no declared bound must report UNMEASURED, never a guessed pass."""
        empty = {**self.style, 'cornice_ratio': {'rule': 'no bound here'}}
        row = rules.check_cornice_ratio(empty, cornice_top_y=20, total_top_y=26)
        self.assertEqual(row['status'], 'UNMEASURED')

    def test_cornice_ratio_passes_inside_the_declared_band_and_fails_outside(self):
        low, high = rules._range_from(self.style['cornice_ratio']['frame_check'])
        inside = rules.check_cornice_ratio(self.style, cornice_top_y=int(26 * (low + high) / 2),
                                           total_top_y=26)
        outside = rules.check_cornice_ratio(self.style, cornice_top_y=int(26 * (high + 0.1)),
                                            total_top_y=26)
        self.assertEqual(inside['status'], 'PASS')
        self.assertEqual(outside['status'], 'FAIL')

    def test_corner_family_accepts_the_default_and_requires_justification_otherwise(self):
        default = rules.check_corner_family(self.style, {'family': 'chamfer'})
        alias = rules.check_corner_family(self.style, {'family': 'turret'})
        justified = rules.check_corner_family(self.style, {'family': 'turret'},
                                              justification='major street junction')
        self.assertEqual(default['status'], 'PASS')
        self.assertEqual(alias['status'], 'FAIL')
        self.assertEqual(justified['status'], 'PASS')

    def test_balcony_levels_accept_many_rows_for_two_roles(self):
        """`balcony_baselines` is emitted per wing AND per group; the rule is about roles."""
        baselines = [{'role': 'lower', 'y': 12}, {'role': 'lower', 'y': 12},
                     {'role': 'upper', 'y': 27}, {'role': 'upper', 'y': 27}]
        row = rules.check_balcony_levels(self.style, baselines,
                                         {'noble_base': 12, 'cornice_base': 27})
        self.assertEqual(row['status'], 'PASS')
        scattered = [{'role': 'lower', 'y': 12}, {'role': 'lower', 'y': 18},
                     {'role': 'upper', 'y': 27}]
        self.assertEqual(rules.check_balcony_levels(
            self.style, scattered, {'noble_base': 12, 'cornice_base': 27})['status'], 'FAIL')

    def test_a_homogeneous_facade_fails_the_composition_rule(self):
        flat = {'north': {'groups': [{'projection': 0, 'role': 'central_pavilion'}]}}
        row = rules.check_composition_hierarchy(self.style, flat, {'projection': 0})
        self.assertEqual(row['status'], 'FAIL')
        pavilion = {'north': {'groups': [{'projection': 2, 'role': 'central_pavilion'}]}}
        self.assertEqual(rules.check_composition_hierarchy(
            self.style, pavilion, {'projection': 0})['status'], 'PASS')

    def test_party_wall_declaration_must_be_explicit(self):
        bare = rules.check_party_walls(self.style, ['north-east-end'], ['street_north'])
        declared = rules.check_party_walls(
            self.style, [{'face': 'north-east-end', 'glazing_allowed': False}],
            [{'face': 'street_north', 'glazing_allowed': True}])
        wrong = rules.check_party_walls(
            self.style, [{'face': 'north-east-end', 'glazing_allowed': True}], [])
        self.assertEqual(bare['status'], 'UNMEASURED')
        self.assertEqual(declared['status'], 'PASS')
        self.assertEqual(wrong['status'], 'FAIL')

    def test_bay_rhythm_allows_one_step_and_rejects_two(self):
        self.assertEqual(rules.check_bay_rhythm(self.style, [4, 5, 5, 4])['status'], 'PASS')
        self.assertEqual(rules.check_bay_rhythm(self.style, [4, 6, 6, 4])['status'], 'FAIL')

    def test_summarize_names_the_failures(self):
        rows = [{'rule': 'a', 'status': 'PASS'}, {'rule': 'b', 'status': 'FAIL'},
                {'rule': 'c', 'status': 'UNMEASURED'}]
        summary = rules.summarize(rows)
        self.assertEqual(summary['status'], 'FAIL')
        self.assertEqual(summary['failed'], ['b'])
        self.assertEqual(summary['unmeasured'], ['c'])


def stamp(role, anchor, size, placed=1, scene_clipped=0):
    return {'id': 'v4:test', 'role': role, 'anchor': list(anchor), 'size_whd': list(size),
            'placed': placed, 'scene_clipped': scene_clipped, 'collisions': {'measured': False}}


ALL_FAMILIES = [
    stamp('base-arcade-north', (0, 0, 0), (4, 6, 3)),
    stamp('bay-noble-north', (0, 12, 0), (4, 13, 2)),
    stamp('balcony-lower-north', (0, 12, 0), (6, 1, 2)),
    stamp('balcony-upper-north', (0, 27, 0), (6, 1, 2)),
    stamp('cornice-north', (0, 27, 0), (6, 1, 3)),
    stamp('roof-north', (0, 29, 0), (6, 4, 10)),
    stamp('dormer-lower-north', (0, 31, 4), (3, 4, 3)),
    stamp('chimney-north', (2, 40, 14), (3, 4, 3)),
    stamp('turret-cap', (0, 27, 0), (13, 20, 15)),
]


class SlotPredicateTests(unittest.TestCase):
    def test_a_complete_plan_passes_every_slot_predicate(self):
        for check in slots.SLOT_CHECKS:
            row = check(ALL_FAMILIES)
            self.assertEqual(row['status'], 'PASS', '%s: %s' % (row['rule'], row['detail']))

    def test_a_slot_that_placed_nothing_fails(self):
        rows = ALL_FAMILIES + [stamp('bay-standard-north', (9, 6, 0), (4, 6, 2), placed=0)]
        row = slots.check_slots_resolved(rows)
        self.assertEqual(row['status'], 'FAIL')
        self.assertEqual(len(row['failures']), 1)

    def test_a_piece_outside_the_scene_fails(self):
        rows = ALL_FAMILIES + [stamp('bay-standard-north', (99, 6, 0), (4, 6, 2),
                                     scene_clipped=12)]
        self.assertEqual(slots.check_scene_fit(rows)['status'], 'FAIL')

    def test_a_missing_family_is_a_spec_omission(self):
        without_chimney = [row for row in ALL_FAMILIES if 'chimney' not in row['role']]
        row = slots.check_required_families(without_chimney)
        self.assertEqual(row['status'], 'FAIL')
        self.assertIn('chimney', row['measured']['missing'])

    def test_a_band_with_a_gap_between_tiles_fails(self):
        rows = [stamp('cornice-north', (0, 27, 0), (6, 1, 3)),
                stamp('cornice-north', (9, 27, 0), (6, 1, 3))]
        row = slots.check_band_continuity(rows)
        self.assertEqual(row['status'], 'FAIL')
        self.assertEqual(row['failures'][0]['gap'], 3)

    def test_an_empty_plan_is_unmeasured_not_passed(self):
        self.assertEqual(slots.check_slots_resolved([])['status'], 'UNMEASURED')

    def test_report_names_the_failed_rules_and_says_what_a_failure_means(self):
        payload = slots.report({'run': 'x', 'stamps': ALL_FAMILIES[:3]},
                               [slots.check_required_families(ALL_FAMILIES[:3])])
        self.assertEqual(payload['status'], 'FAIL')
        self.assertIn('required_families', payload['failed_rules'])
        self.assertIn('spec defect', payload['note'])


if __name__ == '__main__':
    unittest.main()
