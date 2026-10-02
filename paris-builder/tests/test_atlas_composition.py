"""The composition contract must reject architecture that loses its hierarchy."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest

from paris_builder.atlas_composition import (
    composition_for, validate_composition, wing_extra_width)


def plan(**overrides):
    values = {'form': 'corner_house', 'width': 44, 'depth': 40, 'seed': 1901}
    values.update(overrides)
    return SimpleNamespace(**values)


class AtlasCompositionTests(unittest.TestCase):
    def setUp(self):
        self.layout = composition_for(plan(), 6, 5)

    def assert_rejected(self, mutate, message):
        layout = deepcopy(self.layout)
        mutate(layout)
        with self.assertRaisesRegex(ValueError, message):
            validate_composition(layout)

    def test_minimum_wings_keep_recesses_between_both_projected_bays(self):
        layout = composition_for(plan(width=38, depth=35), 5, 4)
        for wing in layout['wings'].values():
            raised = [bay['index'] for bay in wing['bays'] if bay['projection']]
            self.assertEqual(len(raised), 2)
            self.assertGreater(raised[1] - raised[0], 1)
            self.assertEqual(raised[1], wing['bay_count'] - 1)
            self.assertEqual(wing['bays'][0]['projection'], 0)
            self.assertTrue(any(not bay['projection'] for bay in wing['bays']))
        self.assertEqual(layout['corner']['projection'], 1)
        self.assertTrue(layout['corner']['finial'])

    def test_layout_and_budget_remain_consistent_at_larger_even_and_odd_sizes(self):
        for north, west in ((5, 4), (6, 6), (9, 8), (12, 11)):
            layout = composition_for(plan(), north, west)
            for wing in layout['wings'].values():
                bays = wing['bays']
                self.assertGreaterEqual(wing['focal_bay'], 1)
                self.assertLessEqual(wing['focal_bay'], wing['bay_count'] - 3)
                for index, bay in enumerate(bays):
                    if index:
                        self.assertEqual(bay['dormer_grade'] == 'pavilion', bool(bay['projection']))
                    self.assertEqual(bay['plant_accent'], bool(bay['projection']))
                boundary_extra = sum(row['extra_pitch'] for row in wing['pier_boundaries'])
                self.assertEqual(wing['extra_width'], boundary_extra + layout['corner']['origin_margin'])
                self.assertEqual(wing_extra_width(wing['bay_count'], phase=layout['rhythm']['phase']),
                                 wing['extra_width'])
                for row in wing['pier_boundaries']:
                    pitch = layout['rhythm']['pattern'][(layout['rhythm']['phase'] + row['after_bay']) % 4]
                    self.assertEqual(pitch + row['extra_pitch'] - 4, 2)

    def test_chimneys_anchor_to_projected_groups_as_targets_not_source_claims(self):
        for wing in self.layout['wings'].values():
            anchors = wing['chimney_anchors']
            self.assertEqual(len(anchors), 2)
            self.assertEqual({row['bay'] for row in anchors},
                             {bay['index'] for bay in wing['bays'] if bay['projection']})
            for row in anchors:
                self.assertGreaterEqual(row['target_flues'], 4)
                self.assertLessEqual(row['target_flues'], 6)
                self.assertNotIn('flues', row)

    def test_no_block_names_source_ids_or_shutter_variants_enter_design_contract(self):
        encoded = json.dumps(self.layout)
        for forbidden in ('minecraft:', 'v4:', 'st1-', 'shutter_variant'):
            self.assertNotIn(forbidden, encoded)
        self.assertIn('shutter_color_variants_unavailable', self.layout['limitations'])

    def test_json_roundtrip_and_repeated_planning_are_stable(self):
        restored = json.loads(json.dumps(self.layout))
        validate_composition(restored)
        self.assertEqual(restored, composition_for(plan(), 6, 5))

    def test_new_relief_reserves_two_cells_and_reads_historical_layouts(self):
        self.assertEqual(self.layout['schema_version'], 2)
        self.assertEqual(self.layout['corner']['origin_margin'], 2)
        for wing in self.layout['wings'].values():
            self.assertEqual({bay['projection'] for bay in wing['bays']}, {0, 2})
        historical = deepcopy(self.layout)
        historical['schema_version'] = 1
        historical['corner']['origin_margin'] = 1
        for wing in historical['wings'].values():
            wing['extra_width'] -= 1
            for bay in wing['bays']:
                if bay['projection']:
                    bay['projection'] = 1
        validate_composition(historical)
        historical['wings']['north']['bays'][historical['wings']['north']['focal_bay']]['projection'] = 2
        with self.assertRaisesRegex(ValueError, 'projection'):
            validate_composition(historical)

    def test_flat_baseline_is_explicit_and_recoverable_without_mutating_plan(self):
        subject = plan(composition_profile='flat_baseline')
        before = vars(subject).copy()
        baseline = composition_for(subject, 6, 5)
        self.assertEqual(baseline['mode'], 'flat_baseline')
        for wing in baseline['wings'].values():
            self.assertFalse(any(row['projection'] or row['plant_accent'] for row in wing['bays']))
            self.assertEqual(wing['pier_boundaries'], [])
            self.assertEqual(wing['extra_width'], 0)
            self.assertEqual(wing['chimney_anchors'], [])
            self.assertEqual(wing['chimney_policy'], 'legacy_fixed')
        self.assertEqual(baseline['corner']['projection'], 0)
        self.assertFalse(baseline['corner']['finial'])
        self.assertEqual(vars(subject), before)
        self.assertEqual(composition_for(subject, 6, 5, mode='grouped_pavilions'), self.layout)
        self.assertEqual(composition_for(subject, 6, 5), baseline)

    def test_non_corner_small_bay_counts_and_unknown_modes_are_rejected(self):
        cases = ((plan(form='street_house'), 6, 5, None),
                 (plan(), 4, 5, None), (plan(), 5, 3, None),
                 (plan(), 5, 4, 'invented_colorful_windows'))
        for subject, north, west, mode in cases:
            with self.subTest(north=north, west=west, mode=mode):
                with self.assertRaises(ValueError):
                    composition_for(subject, north, west, mode=mode)
        for count in (True, 3, 4.0):
            with self.assertRaises(ValueError):
                wing_extra_width(count)

    def test_groups_cannot_lose_or_duplicate_bays(self):
        for mutation in (lambda r: r['wings']['north']['groups'][0]['bays'].pop(),
                         lambda r: r['wings']['north']['groups'][1]['bays'].append(3)):
            self.assert_rejected(mutation, 'cover|exactly one|contiguous')

    def test_projection_cannot_become_an_independent_decoration_toggle(self):
        self.assert_rejected(lambda r: r['wings']['north']['bays'][1].update(projection=1),
                             'role and projection')

    def test_roof_grade_cannot_ignore_the_projected_facade(self):
        self.assert_rejected(lambda r: r['wings']['north']['bays'][2].update(dormer_grade='ordinary'),
                             'dormer grade')

    def test_plants_cannot_be_scattered_off_the_composition_groups(self):
        self.assert_rejected(lambda r: r['wings']['north']['bays'][1].update(plant_accent=True),
                             'plant accents')

    def test_widened_piers_must_be_at_group_boundaries_and_in_the_width_budget(self):
        self.assert_rejected(lambda r: r['wings']['north']['pier_boundaries'][0].update(after_bay=0),
                             'group boundary')
        self.assert_rejected(lambda r: r['wings']['north'].update(extra_width=0), 'width reserve')

    def test_chimney_targets_cannot_drift_to_a_recess_or_become_isolated_flues(self):
        self.assert_rejected(lambda r: r['wings']['north']['chimney_anchors'][0].update(bay=1),
                             'pavilion focus')
        self.assert_rejected(lambda r: r['wings']['north']['chimney_anchors'][0].update(target_flues=1),
                             'integer >= 4')
        self.assert_rejected(lambda r: r['wings']['north']['chimney_anchors'][0].update(target_flues=7),
                             'four to six')

    def test_malformed_json_fields_fail_with_a_contract_error(self):
        self.assert_rejected(lambda r: r['wings']['north']['bays'][1].update(group=['group-0']),
                             'known group')
        self.assert_rejected(lambda r: r.update(color_strategy='invented_shutter_colors'),
                             'sourced plants only')
        self.assert_rejected(lambda r: r.update(shutter_variant='blue'), 'requires fields')
        self.assert_rejected(lambda r: r['corner'].update(projection=True), 'integer')

    def test_width_budget_changes_with_phase_and_rejects_a_one_cell_boundary_pier(self):
        for phase in range(4):
            layout = composition_for(plan(), 6, 5, phase=phase)
            for wing in layout['wings'].values():
                self.assertEqual(wing['extra_width'], wing_extra_width(wing['bay_count'], phase=phase))
            for boundary in layout['wings']['north']['pier_boundaries']:
                base_pitch = layout['rhythm']['pattern'][(phase + boundary['after_bay']) % 4]
                self.assertEqual(base_pitch + boundary['extra_pitch'], 6)
        self.assert_rejected(lambda r: r['wings']['north']['pier_boundaries'][0].update(extra_pitch=0),
                             'group boundary')


if __name__ == '__main__':
    unittest.main()
