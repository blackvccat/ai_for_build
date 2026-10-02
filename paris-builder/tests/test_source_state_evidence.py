"""Real schematic mutations for source-state provenance and facade coverage."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest

import numpy as np

from paris_builder.architecture import state, transform_state
from paris_builder.exporter import write_schematic
from paris_builder.source_state_evidence import audit, special_category, validate


class SourceStateEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'reference.schem'
        self.sample = self.root / 'detail.schem'
        self.target = self.root / 'candidate.schem'
        self.source_states = [
            state('iron_door', facing='east', half='lower', hinge='left', open='false', powered='false'),
            state('iron_door', facing='west', half='lower', hinge='right', open='false', powered='false'),
            state('diorite_wall', north='none', east='tall', south='none', west='none', up='false', waterlogged='false'),
            state('smooth_sandstone_stairs', facing='east', half='top', shape='inner_left', waterlogged='false'),
        ]
        write_schematic(self.source, np.array([[[0, 1, 2, 3]]], dtype=np.int32), self.source_states)
        write_schematic(self.sample, np.array([[[0, 1, 2, 3]]], dtype=np.int32), self.source_states)
        self.records = {'v3:fixture': {'source': str(self.source), 'source_sha256': self.sha(self.source),
                                     'outside': 'south/+z', 'clean_origin_source_xyz': [0, 0, 0],
                                     '_sample_path': str(self.sample)}}
        self.manifest = {
            'source_state_requirements': {'required_categories': ['thin_door_window', 'single_arm_wall', 'shaped_stair'],
                                          'required_faces': ['street_north', 'street_east'],
                                          'coverage': 'all_street_residential_openings'},
            'openings': [{'face': 'street_north', 'floor': 1, 'u': 4, 'y': 3, 'width': 2, 'height': 3, 'kind': 'window'},
                         {'face': 'street_east', 'floor': 1, 'u': 6, 'y': 3, 'width': 2, 'height': 3, 'kind': 'window'}],
            'decorative_doors': [], 'source_state_audit': [],
        }
        self.volume = np.zeros((11, 15, 15), dtype=np.int32)
        self.palette = ['minecraft:air', 'minecraft:sandstone']
        self.volume[0, 2:13, 2:12] = 1
        for ident, opening in enumerate(self.manifest['openings']):
            turns = 2 if opening['face'] == 'street_north' else 3
            for y in range(3, 6):
                for offset in range(2):
                    self.place(ident, offset, 'thin_door_window', opening['u'] + offset, y, 1, turns)
            self.place(ident, 2, 'single_arm_wall', opening['u'] - 1, 3, -1, turns)
            self.place(ident, 3, 'shaped_stair', opening['u'] - 1, 6, -1, turns)
        self.export()

    @staticmethod
    def sha(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def place(self, opening_id, source_x, role, u, y, depth, turns):
        opening = self.manifest['openings'][opening_id]
        xyz = [u, y, 2 + depth] if opening['face'] == 'street_north' else [11 - depth, y, u]
        value = transform_state(self.source_states[source_x], turns=turns)
        if value not in self.palette:
            self.palette.append(value)
        self.volume[y, xyz[2], xyz[0]] = self.palette.index(value)
        self.manifest['source_state_audit'].append({
            'source_id': 'v3:fixture', 'source_path': str(self.source), 'source_sha256': self.sha(self.source),
            'sample_sha256': self.sha(self.sample), 'source_local_xyz': [source_x, 0, 0],
            'source_xyz': [source_x, 0, 0], 'original_state': self.source_states[source_x],
            'transformed_state': value, 'target_xyz': xyz, 'turns': turns, 'mirror': False,
            'role': role, 'face': opening['face'], 'storey': 1, 'opening_id': opening_id,
        })
        if role == 'thin_door_window':
            self.manifest['decorative_doors'].append({'xyz': xyz, 'state': value})

    def export(self):
        write_schematic(self.target, self.volume, self.palette)

    def report(self, manifest=None, required=True):
        return audit(self.target, manifest or self.manifest, required=required,
                     source_roots=[self.root], source_records=self.records)

    def assert_failure(self, text, manifest=None):
        result = self.report(manifest)
        self.assertEqual(result['status'], 'FAIL')
        self.assertIn(text, '\n'.join(result['failures']))
        return result

    def test_real_reference_states_cover_both_facades_and_remain_game_pending(self):
        result = self.report()
        self.assertEqual(result['status'], 'PASS', result['failures'])
        self.assertEqual(result['matched'], 16)
        self.assertEqual(result['source_special_categories'],
                         {'thin_door_window': 12, 'single_arm_wall': 2, 'shaped_stair': 2})
        self.assertTrue(all(row['status'] == 'PASS' for row in result['opening_coverage']))
        self.assertEqual(result['game_acceptance'], 'PENDING')
        self.assertEqual(validate(result, self.target, self.manifest, required=True,
                                  source_roots=[self.root], source_records=self.records), result)

    def test_ordinary_state_inventory_is_not_a_special_construction_method(self):
        self.assertIsNone(special_category(state('sandstone_slab', type='top', waterlogged='false')))
        self.assertIsNone(special_category(state('sandstone_stairs', half='top', shape='straight')))
        self.assertIsNone(special_category(self.source_states[0]))
        self.assertIsNone(special_category(state('diorite_wall', up='false', north='none', east='none', south='none', west='none')))
        self.assertIsNone(special_category(state('diorite_wall', up='false', north='tall', east='tall', south='tall', west='tall')))
        result = self.report()
        self.assertEqual(result['stateful_inventory']['door'], 12)
        self.assertEqual(result['source_special_categories']['thin_door_window'], 12)

    def test_export_mutation_and_total_overwrite_fail_source_survival(self):
        for row in self.manifest['source_state_audit']:
            x, y, z = row['target_xyz']
            self.volume[y, z, x] = 1
        self.export()
        result = self.assert_failure('missing, overwritten, or changed')
        self.assertEqual(result['matched'], 0)

    def test_one_matching_import_cannot_cover_all_windows_or_both_streets(self):
        manifest = deepcopy(self.manifest)
        manifest['source_state_audit'] = manifest['source_state_audit'][:1]
        result = self.assert_failure('incomplete source-method coverage', manifest)
        self.assertEqual(result['matched'], 1)

    def test_a_missing_leaf_cannot_hide_behind_category_presence(self):
        manifest = deepcopy(self.manifest)
        manifest['source_state_audit'].pop(1)
        result = self.assert_failure('incomplete source-method coverage', manifest)
        self.assertEqual(result['opening_coverage'][0]['missing_thin_window_cells'], 1)

    def test_wrong_source_coordinate_hash_and_transform_are_independently_rejected(self):
        cases = [('source_xyz', [3, 0, 0], 'claimed original state'),
                 ('source_sha256', '0' * 64, 'hash changed'),
                 ('sample_sha256', '0' * 64, 'sample hash changed'),
                 ('turns', 0, 'rotate onto the stated facade'),
                 ('transformed_state', self.source_states[0], 'allowed source transform'),
                 ('source_local_xyz', [1, 0, 0], 'local coordinate differs')]
        for key, value, message in cases:
            with self.subTest(key=key):
                manifest = deepcopy(self.manifest)
                manifest['source_state_audit'][0][key] = value
                self.assert_failure(message, manifest)

    def test_generated_export_and_unapproved_files_cannot_become_sources(self):
        manifest = deepcopy(self.manifest)
        manifest['source_state_audit'][0]['source_path'] = str(self.target)
        self.assert_failure('cannot be its own reference', manifest)
        untrusted = audit(self.target, self.manifest, required=True, source_records=self.records)
        self.assertEqual(untrusted['status'], 'FAIL')
        self.assertIn('outside the read-only reference roots', '\n'.join(untrusted['failures']))

    def test_duplicate_cells_wrong_face_and_undeclared_half_doors_fail(self):
        manifest = deepcopy(self.manifest)
        manifest['source_state_audit'].append(deepcopy(manifest['source_state_audit'][0]))
        self.assert_failure('Duplicate target', manifest)
        manifest = deepcopy(self.manifest)
        manifest['source_state_audit'][0]['face'] = 'street_east'
        self.assert_failure('rotate onto the stated facade', manifest)
        manifest = deepcopy(self.manifest)
        manifest['decorative_doors'].pop(0)
        self.assert_failure('explicitly declared as decorative', manifest)

    def test_single_point_at_wrong_position_cannot_claim_window_detail(self):
        manifest = deepcopy(self.manifest)
        row = manifest['source_state_audit'][-1]
        x, y, z = row['target_xyz']
        self.volume[y, z, x] = 0
        row['target_xyz'] = [7, 8, 7]
        self.volume[8, 7, 7] = self.palette.index(row['transformed_state'])
        self.export()
        self.assert_failure('outside the declared window construction position', manifest)

    def test_forged_pass_is_recomputed_and_changed_reference_cannot_reuse_receipt(self):
        report = self.report()
        forged = deepcopy(report)
        forged['matched'] += 1
        with self.assertRaisesRegex(ValueError, 'independently recomputed'):
            validate(forged, self.target, self.manifest, required=True,
                     source_roots=[self.root], source_records=self.records)
        self.source_states[0] = 'minecraft:stone'
        write_schematic(self.source, np.array([[[0, 1, 2, 3]]], dtype=np.int32), self.source_states)
        with self.assertRaisesRegex(ValueError, 'independently recomputed'):
            validate(report, self.target, self.manifest, required=True,
                     source_roots=[self.root], source_records=self.records)

    def test_optional_empty_report_is_explicit_and_final_empty_report_fails(self):
        manifest = {'openings': self.manifest['openings']}
        self.assertEqual(self.report(manifest, required=False)['status'], 'NOT_REQUIRED')
        self.assert_failure('Final tier requires explicit', manifest)
        with self.assertRaisesRegex(ValueError, 'manifest or validator changed'):
            report = self.report()
            changed = deepcopy(self.manifest)
            changed['openings'][0]['width'] = 1
            validate(report, self.target, changed, required=True,
                     source_roots=[self.root], source_records=self.records)

    def test_malformed_requirements_and_opening_claims_fail_without_crashing(self):
        manifest = deepcopy(self.manifest)
        manifest['source_state_requirements']['required_categories'] = None
        self.assert_failure('name all three scoped methods', manifest)
        manifest = deepcopy(self.manifest)
        manifest['openings'][0] = None
        self.assert_failure('invalid opening schedule row', manifest)
        manifest = deepcopy(self.manifest)
        manifest['source_state_audit'][0]['source_xyz'] = [False, 0, 0]
        self.assert_failure('three integer', manifest)

    def test_straight_header_fillers_are_verified_but_cannot_replace_shaped_ends(self):
        self.source_states[3] = state('smooth_sandstone_stairs', facing='east', half='top',
                                      shape='straight', waterlogged='false')
        write_schematic(self.source, np.array([[[0, 1, 2, 3]]], dtype=np.int32), self.source_states)
        write_schematic(self.sample, np.array([[[0, 1, 2, 3]]], dtype=np.int32), self.source_states)
        self.records['v3:fixture']['source_sha256'] = self.sha(self.source)
        for row in self.manifest['source_state_audit']:
            row['source_sha256'] = self.sha(self.source)
            row['sample_sha256'] = self.sha(self.sample)
            if row['role'] == 'shaped_stair':
                row['original_state'] = self.source_states[3]
                value = transform_state(self.source_states[3], turns=row['turns'])
                row['transformed_state'] = value
                self.palette.append(value)
                x, y, z = row['target_xyz']
                self.volume[y, z, x] = len(self.palette) - 1
        self.export()
        result = self.assert_failure('incomplete source-method coverage')
        self.assertEqual(result['matched'], result['declared'])
        self.assertEqual(result['matched_ordinary_header_cells'], 2)
        self.assertNotIn('shaped_stair', result['source_special_categories'])


if __name__ == '__main__':
    unittest.main()
