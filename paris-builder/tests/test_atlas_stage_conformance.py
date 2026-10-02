"""North/west stage gates react to exported geometry, not detail paperwork."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from paris_builder.architectural_conformance import measure, validate
from paris_builder.exporter import write_schematic
from paris_builder.facade_section import measure as measure_section


class AtlasStageConformanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'candidate.schem'
        self.palette = ['minecraft:air', 'minecraft:smooth_sandstone',
                        'minecraft:deepslate_tiles', 'minecraft:glass']
        self.volume = np.zeros((15, 14, 14), dtype=np.int32)
        self.body_north = [4, 0, 2, 14, 8, 8]
        self.body_west = [2, 0, 4, 8, 8, 14]
        self.corner_body = [0, 0, 0, 6, 8, 6]
        self.corner_cap = [0, 8, 0, 4, 12, 4]
        self.box(self.body_north, 1)
        self.box(self.body_west, 1)
        self.box(self.corner_body, 1)
        profile = [0, 1, 2, 2, 2, 2]
        for depth, top in enumerate(profile):
            self.box([4, 8, 2 + depth, 14, 9 + top, 3 + depth], 2)
            self.box([2 + depth, 8, 4, 3 + depth, 9 + top, 14], 2)
        self.box(self.corner_cap, 2)
        north_glass = [[10, y, 2] for y in range(2, 5)]
        west_glass = [[2, y, 10] for y in range(2, 5)]
        for x, y, z in north_glass + west_glass:
            self.volume[y, z, x] = 3
        self.plan = {
            'form': 'corner_house', 'detail_profile': 'atlas_street1',
            'composition_profile': 'grouped_pavilions', 'width': 14, 'depth': 14,
            'composition': {'corner': {'projection': 1}},
            'atlas_tier_semantics': 'bare_massing',
            'atlas_frame_spec': {
                'schema_version': 1, 'stage': 'frameworks', 'street_faces': ['north', 'west'],
                'bounds_xyz_half_open': [0, 0, 0, 14, 15, 14],
                'occupied_envelope_upper_xyz': [14, 12, 14], 'origin_xyz': [0, 0, 0],
                'wing_segments': [
                    {'wing': 'north', 'role': 'middle_recess', 'group': 'n', 'projection': 0,
                     'axis_interval': [4, 14], 'wall_front': 2, 'roof_front': 2,
                     'body_bbox_xyz_half_open': self.body_north,
                     'roof_bbox_xyz_half_open': [4, 8, 2, 14, 11, 8]},
                    {'wing': 'west', 'role': 'middle_recess', 'group': 'w', 'projection': 0,
                     'axis_interval': [4, 14], 'wall_front': 2, 'roof_front': 2,
                     'body_bbox_xyz_half_open': self.body_west,
                     'roof_bbox_xyz_half_open': [2, 8, 4, 8, 11, 14]},
                ],
                'party_faces': [
                    {'axis': 'x', 'coordinate': 13, 'bbox_xyz_half_open': [13, 0, 2, 14, 8, 8]},
                    {'axis': 'z', 'coordinate': 13, 'bbox_xyz_half_open': [2, 0, 13, 8, 8, 14]},
                ],
                'roof_profile': {'datum_y': 8, 'depth_local_top_y': profile},
                'roof_joint_bbox_xyz_half_open': [4, 8, 4, 8, 11, 8],
                'corner': {'body_bbox_xyz_half_open': self.corner_body,
                           'cap_bbox_xyz_half_open': self.corner_cap, 'cap_top_y': 11},
                'openings': [
                    {'wing': 'north', 'role': 'standard', 'outward': '-z', 'stage_scope': 'all',
                     'bbox_xyz_half_open': [10, 2, 2, 11, 5, 3], 'glass_cells_xyz': north_glass},
                    {'wing': 'west', 'role': 'standard', 'outward': '-x', 'stage_scope': 'all',
                     'bbox_xyz_half_open': [2, 2, 10, 3, 5, 11], 'glass_cells_xyz': west_glass},
                ],
            },
        }

    def box(self, box, state):
        x0, y0, z0, x1, y1, z1 = box
        self.volume[y0:y1, z0:z1, x0:x1] = state

    def receipt(self, plan=None, stage='frameworks', section=None):
        write_schematic(self.path, self.volume, self.palette)
        return measure(self.path, plan or self.plan, section, stage=stage)

    @staticmethod
    def check(report, ident):
        return next(row for row in report['checks'] if row['id'] == ident)

    def test_framework_dispatch_is_north_west_and_needs_no_source_stamps(self):
        report = self.receipt()
        self.assertEqual(report['policy_id'], 'export-atlas-nw-stage-v1')
        self.assertEqual(report['status'], 'PASS', report['checks'])
        self.assertEqual(self.check(report, 'atlas/topology/north_west_streets')['status'], 'pass')
        self.assertNotIn('atlas/source_detail/schema', {row['id'] for row in report['checks']})
        self.assertEqual(validate(report, self.path, self.plan, stage='frameworks'), report)

    def test_removing_west_wing_is_rejected_even_with_fine_detail_metadata(self):
        self.box([2, 0, 8, 8, 8, 14], 0)
        plan = deepcopy(self.plan)
        plan['source_trace'] = {'status': 'PASS', 'verified_stamps': 9000}
        plan['atlas_audit'] = {'status': 'PASS', 'matched_cells': 999999}
        plan['techniques'] = [{'role': 'fine_window', 'status': 'PASS'}] * 10
        report = self.receipt(plan, stage='tier3')
        self.assertEqual(self.check(report, 'atlas/body/1')['status'], 'fail')
        self.assertEqual(report['status'], 'FAIL')

    def test_party_skin_hole_is_rejected_at_any_height(self):
        self.volume[3, 6, 13] = 0
        report = self.receipt()
        check = self.check(report, 'atlas/party/0')
        self.assertEqual(check['status'], 'fail')
        self.assertIn([13, 3, 6], check['coordinates']['violations_xyz'])

    def test_flattened_roof_fails_actual_profile(self):
        self.box([4, 8, 2, 14, 11, 8], 0)
        self.box([2, 8, 4, 8, 11, 14], 0)
        self.box([4, 8, 2, 14, 9, 8], 2)
        self.box([2, 8, 4, 8, 9, 14], 2)
        report = self.receipt()
        self.assertEqual(self.check(report, 'atlas/roof/profile/north')['status'], 'fail')
        self.assertEqual(self.check(report, 'atlas/roof/profile/west')['status'], 'fail')

    def test_removed_corner_body_cannot_be_rescued_by_retained_cap(self):
        self.box(self.corner_body, 0)
        report = self.receipt()
        self.assertEqual(self.check(report, 'atlas/corner/body_projection')['status'], 'fail')
        self.assertEqual(self.check(report, 'atlas/corner/control_height')['status'], 'pass')

    def test_cube_in_glazing_corridor_fails_opening_even_if_glass_remains(self):
        self.volume[3, 1, 10] = 1
        report = self.receipt()
        self.assertEqual(self.check(report, 'atlas/opening/0')['status'], 'fail')
        self.assertEqual(self.check(report, 'atlas/opening/0')['actual']['missing_glazing'], 0)
        self.assertEqual(self.check(report, 'atlas/opening/0')['actual']['known_full_cube_blockers'], 1)

    def native_north_window(self):
        """A source leaf pair replaces the framework's transparent placeholder."""
        first = 'minecraft:iron_door[facing=east,half=lower,hinge=right,open=false,powered=false]'
        second = 'minecraft:iron_door[facing=west,half=lower,hinge=left,open=false,powered=false]'
        self.palette.extend([first, second])
        cells = [[x, y, 2] for y in range(2, 5) for x in (10, 11)]
        self.plan['atlas_frame_spec']['openings'][0].update(
            glass_cells_xyz=cells, bbox_xyz_half_open=[10, 2, 2, 12, 5, 3])
        for x, y, z in cells:
            self.volume[y, z, x] = 4 if x == 10 else 5
        return cells

    def test_native_detail_reads_sculpted_surface_without_inventing_glass(self):
        self.native_north_window()
        report = self.receipt(stage='tier3')
        check = self.check(report, 'atlas/opening/0')
        self.assertEqual(check['status'], 'pass')
        self.assertIsNone(check['actual']['missing_glazing'])
        self.assertEqual(check['actual']['wrong_native_leaf_states'], 0)
        self.assertEqual(self.check(report, 'atlas/opening/0/partial_visibility')['status'], 'unsupported')
        self.assertFalse(self.check(report, 'atlas/opening/0/partial_visibility')['required'])

    def test_deleted_source_leaf_is_rejected_despite_other_leaves_and_fake_audit(self):
        self.native_north_window()
        self.volume[3, 2, 10] = 0
        self.plan['source_trace'] = {'status': 'PASS', 'verified_stamps': 9000}
        check = self.check(self.receipt(stage='tier3'), 'atlas/opening/0')
        self.assertEqual(check['status'], 'fail')
        self.assertEqual(check['actual']['wrong_native_leaf_states'], 1)
        self.assertEqual(check['coordinates']['missing'][0]['xyz'], [10, 3, 2])

    def test_source_leaf_with_wrong_orientation_is_rejected(self):
        self.native_north_window()
        self.palette.append('minecraft:iron_door[facing=north,half=lower,hinge=right,open=false,powered=false]')
        self.volume[3, 2, 10] = 6
        check = self.check(self.receipt(stage='tier3'), 'atlas/opening/0')
        self.assertEqual(check['status'], 'fail')
        self.assertEqual(check['actual']['wrong_native_leaf_states'], 1)

    def test_detail_window_keeps_opaque_corridor_gate_after_materialization(self):
        self.native_north_window()
        self.volume[3, 1, 10] = 1
        check = self.check(self.receipt(stage='tier3'), 'atlas/opening/0')
        self.assertEqual(check['status'], 'fail')
        self.assertEqual(check['actual']['wrong_native_leaf_states'], 0)
        self.assertEqual(check['actual']['known_full_cube_blockers'], 1)

    def test_native_stepped_sill_contact_does_not_authorize_other_foreground_cubes(self):
        cells = self.native_north_window()
        self.palette.append('minecraft:cut_sandstone')
        opening = self.plan['atlas_frame_spec']['openings'][0]
        opening['role'] = 'noble_lower'
        opening['bbox_xyz_half_open'][5] = 4
        for point in cells:
            if point[1] == 2:
                point[2] = 3
                self.volume[2, 3, point[0]] = 5 if point[0] == 10 else 4
                self.volume[2, 2, point[0]] = 6
        check = self.check(self.receipt(stage='tier3'), 'atlas/opening/0')
        self.assertEqual(check['status'], 'pass')
        self.assertEqual(check['actual']['native_sill_contacts'], 2)
        self.volume[3, 1, 10] = 6
        check = self.check(self.receipt(stage='tier3'), 'atlas/opening/0')
        self.assertEqual(check['status'], 'fail')
        self.assertEqual(check['actual']['native_sill_contacts'], 2)
        self.assertEqual(check['actual']['known_full_cube_blockers'], 1)
        self.volume[3, 1, 10] = 0
        self.volume[2, 2, 10] = 0
        check = self.check(self.receipt(stage='tier3'), 'atlas/opening/0/native_sill_contact')
        self.assertEqual(check['status'], 'fail')
        self.assertEqual(check['actual']['incorrect_sill_cells'], 1)

    def native_roof_edge(self, *, wrong_direction=False):
        states = ('[east=none,north=low,south=low,up=false,waterlogged=false,west=none]'
                  if wrong_direction else
                  '[east=low,north=none,south=none,up=false,waterlogged=false,west=low]')
        self.palette.append('minecraft:deepslate_brick_wall' + states)
        self.volume[10, 4, 8:14] = len(self.palette) - 1

    def test_detail_low_roof_edge_retains_strict_source_voxel_layer(self):
        self.native_roof_edge()
        check = self.check(self.receipt(stage='tier3'), 'atlas/roof/profile/north')
        self.assertEqual(check['status'], 'pass')
        observed = next(row for row in check['actual']['profile'] if row['depth'] == 2)
        self.assertEqual(observed['actual_modal_top_y'], 10)
        self.assertEqual(observed['expected_top_y'], 10)

    def test_unrelated_or_unsupported_dark_wall_cannot_fake_roof_edge(self):
        self.native_roof_edge(wrong_direction=True)
        check = self.check(self.receipt(stage='tier3'), 'atlas/roof/profile/north')
        self.assertEqual(check['status'], 'fail')
        self.assertIn(2, check['actual']['mismatched_depths'])
        self.volume[10, 4, 8:14] = 0
        self.native_roof_edge()
        self.volume[9, 4, 8:14] = 0
        check = self.check(self.receipt(stage='tier3'), 'atlas/roof/profile/north')
        self.assertEqual(check['status'], 'fail')
        self.assertIn(2, check['actual']['mismatched_depths'])

    def test_cached_auxiliary_section_with_old_export_hash_is_rejected(self):
        self.receipt()
        section = measure_section(self.path)
        self.volume[3, 1, 10] = 1
        with self.assertRaisesRegex(ValueError, 'stale or belongs to another atlas export'):
            self.receipt(section=section)

    def test_rehashed_forged_receipt_cannot_override_geometry_when_recomputed(self):
        report = self.receipt()
        self.volume[3, 6, 13] = 0
        write_schematic(self.path, self.volume, self.palette)
        broken = measure(self.path, self.plan, stage='frameworks')
        forged = deepcopy(broken)
        for check in forged['checks']:
            if check['status'] == 'fail':
                check['status'] = 'pass'
        forged['summary'] = {'pass': len(forged['checks']), 'fail': 0, 'unsupported': 0,
                             'required_fail': 0, 'required_unsupported': 0}
        forged['status'] = 'PASS'
        with self.assertRaisesRegex(ValueError, 'differs from independently recomputed'):
            validate(forged, self.path, self.plan, stage='frameworks')
        self.assertEqual(report['status'], 'PASS')

    def test_json_roundtrip_and_validator_digest_remain_bound(self):
        report = json.loads(json.dumps(self.receipt()))
        self.assertEqual(validate(report, self.path, self.plan, stage='frameworks'), report)
        report['validator_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'stale atlas'):
            validate(report, self.path, self.plan, stage='frameworks')


if __name__ == '__main__':
    unittest.main()
