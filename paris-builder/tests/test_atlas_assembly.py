"""Source-backed atlas transforms and export audits under frozen block states."""
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from paris_builder import atlas_assembly as atlas
from paris_builder import technique_library as library
from paris_builder.architecture import Scene, transform_state
from paris_builder.exporter import write_schematic
from paris_builder.schematic import load_schematic


DOOR = 'minecraft:iron_door[facing=north,half=lower,hinge=left,open=false,powered=false]'
WALL = 'create:cut_calcite_wall[east=low,north=none,south=tall,up=false,waterlogged=false,west=none]'
STAIR = 'minecraft:sandstone_stairs[facing=north,half=top,shape=outer_left,waterlogged=false]'


class AtlasTransformTests(unittest.TestCase):
    def test_rotation_changes_coordinates_and_all_directional_states(self):
        palette = ['minecraft:air', STAIR, DOOR, WALL]
        volume = np.array([[[1, 2, 0], [0, 0, 3]]], dtype=np.int32)
        rotated, states = atlas.rotate_volume(volume, palette, 1)
        self.assertEqual(rotated.shape, (1, 3, 2))
        self.assertEqual(states[int(rotated[0, 0, 1])], transform_state(STAIR, turns=1))
        self.assertEqual(states[int(rotated[0, 1, 1])], transform_state(DOOR, turns=1))
        self.assertEqual(states[int(rotated[0, 2, 0])], transform_state(WALL, turns=1))
        self.assertIn('half=lower', states[int(rotated[0, 1, 1])])

    def test_nonzero_air_id_does_not_remove_stairs(self):
        volume = np.array([[[0, 1]]], dtype=np.int32)
        rotated, palette = atlas.rotate_volume(volume, [STAIR, 'minecraft:void_air'], 3)
        self.assertEqual(rotated.size, 1)
        self.assertEqual(palette[int(rotated[0, 0, 0])], transform_state(STAIR, turns=3))

    def test_explicit_wall_replacement_preserves_other_mod_blocks(self):
        volume = np.array([[[0, 1, 2]]], dtype=np.int32)
        other = 'create:brass_block'
        rewritten, palette, count = atlas.patch_wall_states(volume, [WALL, other, DOOR])
        self.assertEqual(count, 1)
        self.assertEqual(palette[int(rewritten[0, 0, 0])],
                         WALL.replace('create:cut_calcite_wall', 'minecraft:diorite_wall'))
        self.assertEqual(palette[int(rewritten[0, 0, 1])], other)
        self.assertEqual(palette[int(rewritten[0, 0, 2])], DOOR)
        with self.assertRaisesRegex(ValueError, 'not explicitly allowed'):
            atlas.patch_wall_states(volume, [WALL, other, DOOR], 'minecraft:stone')

    def test_wall_replacement_rejects_unrecognized_properties(self):
        with self.assertRaisesRegex(ValueError, 'unsupported frozen wall'):
            atlas.patch_wall_states(np.zeros((1, 1, 1), np.int32), ['create:cut_calcite_wall'])

    def test_invalid_subcuts_and_air_only_rotations_are_rejected(self):
        volume = np.ones((1, 1, 2), np.int32)
        for bounds in [(-1, 1, 0, 1, 0, 1), (0, 3, 0, 1, 0, 1), (1, 1, 0, 1, 0, 1)]:
            with self.assertRaises(ValueError):
                atlas.subcut_volume(volume, ['minecraft:air', DOOR], *bounds)
        with self.assertRaisesRegex(ValueError, 'all air'):
            atlas.rotate_volume(np.zeros((1, 1, 1), np.int32), ['minecraft:air'], 1)


class DerivedProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'project'
        self.folder = self.root / 'knowledge/library-v4/atlas-techniques/fixture'
        self.folder.mkdir(parents=True)
        self.ident = 'v4:fixture'
        self.volume = np.array([[[0, 1]]], dtype=np.int32)
        self.palette = [DOOR, STAIR]
        self.source = self.root.parent / 'source.schem'
        source_info = write_schematic(self.source, self.volume, self.palette)
        info = write_schematic(self.folder / 'detail.schem', self.volume, self.palette)
        self.record = {'source': 'source.schem', 'source_sha256': source_info['sha256'],
                       'schematic_sha256': info['sha256'], 'clean_origin_source_xyz': [0, 0, 0],
                       'source_bbox_xyz_half_open': [0, 0, 0, 2, 1, 1], 'cleaning': {}}
        self.write_record()
        self.rows = [{'id': self.ident, 'path': 'knowledge/library-v4/atlas-techniques/fixture/detail.schem'}]
        for patcher in (patch.object(atlas, 'ROOT', self.root),
                        patch.object(atlas, 'V4_DIR', self.folder.parent),
                        patch.object(library, 'ROOT', self.root),
                        patch.object(library, 'catalogue', return_value={'entries': self.rows}),
                        patch.object(atlas, 'validate_vanilla', return_value={'status': 'PASS'})):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.asm = atlas.Assembler(Scene(7, 3, 7), self.root / 'runs/test/derived')

    def write_record(self):
        (self.folder / 'record.json').write_text(json.dumps(self.record), encoding='utf-8')

    def derive(self):
        volume, palette = atlas.rotate_volume(self.volume, self.palette, 3)
        self.asm.register_derived('derived:fixture@r3', volume, palette, 'rotate source',
                                  source_id=self.ident, operations=[{'op': 'rotate', 'turns': 3}])
        return volume, palette

    def test_derived_output_reproduces_from_original_and_retains_lower_door(self):
        self.derive()
        self.asm.stamp('derived:fixture@r3', 1, 1, 1, 'window')
        row = self.asm.derived['derived:fixture@r3']
        self.assertEqual(row['nonair_cells'], 2)  # palette zero contains a real door
        self.assertEqual(row['provenance']['source_evidence']['original_source_sha256'],
                         hashlib.sha256(self.source.read_bytes()).hexdigest())
        report = library.verify_stamp_audit(self.asm.scene, self.asm.audit_entries(), self.asm.audit_rows())
        self.assertEqual(report['status'], 'PASS')
        self.assertIn('half=lower', self.asm.scene.palette[int(self.asm.scene.volume[1, 2, 1])])

    def test_registration_rejects_missing_provenance_and_unrecorded_door_repair(self):
        with self.assertRaisesRegex(ValueError, 'source_id'):
            self.asm.register_derived('derived:fake', self.volume, self.palette, 'self assertion')
        with self.assertRaisesRegex(ValueError, 'differs from declared'):
            self.asm.register_derived('derived:fake', self.volume,
                                      [DOOR.replace('half=lower', 'half=upper'), STAIR], 'repair',
                                      source_id=self.ident, operations=[])

    def test_tampering_original_invalidates_derived_before_stamp(self):
        self.derive()
        write_schematic(self.source, self.volume, ['minecraft:stone', STAIR])
        with self.assertRaisesRegex(ValueError, 'original source hash'):
            self.asm.stamp('derived:fixture@r3', 1, 1, 1, 'window')
        self.assertFalse(self.asm.stamps)

    def test_rehashed_library_edit_still_fails_original_source_comparison(self):
        info = write_schematic(self.folder / 'detail.schem', self.volume, ['minecraft:stone', STAIR])
        self.record['schematic_sha256'] = info['sha256']
        self.write_record()
        with self.assertRaisesRegex(ValueError, 'differs from original'):
            self.asm.register_derived('derived:fake', self.volume, ['minecraft:stone', STAIR], 'edit',
                                      source_id=self.ident, operations=[])

    def test_export_audit_rejects_tampered_derivative(self):
        self.derive()
        self.asm.stamp('derived:fixture@r3', 1, 1, 1, 'window')
        row = self.asm.derived['derived:fixture@r3']
        write_schematic(self.root / row['path'], np.ones((1, 2, 1), np.int32),
                        ['minecraft:air', 'minecraft:stone'])
        report = library.verify_stamp_audit(self.asm.scene, self.asm.audit_entries(), self.asm.audit_rows())
        self.assertEqual(report['status'], 'FAIL')
        self.assertIn('changed after registration', report['stamps'][0]['reason'])

    def test_stamp_collision_log_distinguishes_identical_overlap_from_change(self):
        self.asm.stamp(self.ident, 1, 1, 1, 'first')
        same = self.asm.stamp(self.ident, 1, 1, 1, 'second')
        self.assertEqual(same['collisions']['same_state_overlap'], 2)
        self.assertEqual(same['collisions']['different_state_overwrites'], 0)
        changed = self.asm.stamp(self.ident, 2, 1, 1, 'shifted')
        self.assertEqual(changed['collisions']['different_state_overwrites'], 1)

    def test_unrequested_scene_clipping_remains_an_audit_failure(self):
        row = self.asm.stamp(self.ident, 6, 1, 1, 'edge')
        self.assertEqual(row['scene_clipped'], 1)
        report = library.verify_stamp_audit(self.asm.scene, self.asm.audit_entries(), self.asm.audit_rows())
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(report['stamps'][0]['unauthorized_clip'], 1)


class StampAuditPolicyTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{'id': 'fixture:a', 'path': 'unused'}, {'id': 'fixture:b', 'path': 'unused'}]
        self.sources = {ident: SimpleNamespace(volume=np.zeros((1, 1, 2), np.int32),
                                              id_to_state=[value], air_ids=[])
                        for ident, value in [('fixture:a', 'minecraft:stone'),
                                             ('fixture:b', 'minecraft:diorite')]}
        patcher = patch.object(library, 'load_detail', side_effect=lambda ident, rows=None: self.sources[ident])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.scene = Scene(4, 1, 1)
        self.scene.put(0, 0, 0, 'minecraft:stone')
        self.scene.put(1, 0, 0, 'minecraft:diorite')
        self.scene.put(2, 0, 0, 'minecraft:diorite')
        self.claims = [{'id': 'fixture:a', 'x': 0, 'role': 'bay'},
                       {'id': 'fixture:b', 'x': 1, 'role': 'cornice'}]
        self.rules = [{'from_role': 'bay', 'to_role': 'cornice', 'reason': 'same layer junction',
                       'bbox_xyz_half_open': [1, 0, 0, 2, 1, 1]}]

    def test_later_overwrite_requires_explicit_role_and_region_permission(self):
        strict = library.verify_stamp_audit(self.scene, self.claims, self.rows)
        self.assertEqual(strict['status'], 'FAIL')
        self.assertEqual(strict['stamps'][0]['overwritten_by_later_stamp'], 1)
        bare_flag = library.verify_stamp_audit(self.scene, self.claims, self.rows, allow_overwrites=True)
        self.assertEqual(bare_flag['status'], 'FAIL')
        permitted = library.verify_stamp_audit(self.scene, self.claims, self.rows,
                                              allow_overwrites=True, allowed_overwrites=self.rules)
        self.assertEqual(permitted['status'], 'PASS')
        self.assertEqual(permitted['authorized_overwritten_cells'], 1)

    def test_fully_lost_piece_never_passes_as_a_real_library_stamp(self):
        self.scene.put(0, 0, 0, 'minecraft:diorite')
        self.claims[1]['x'] = 0
        report = library.verify_stamp_audit(self.scene, self.claims, self.rows, allow_overwrites=True,
                                           allowed_overwrites=[dict(self.rules[0], bbox_xyz_half_open=None)])
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(report['fully_lost_stamps'], 1)

    def test_final_export_drift_cannot_be_explained_by_a_later_stamp(self):
        self.scene.put(1, 0, 0, 'minecraft:gold_block')
        report = library.verify_stamp_audit(self.scene, self.claims, self.rows, allow_overwrites=True,
                                           allowed_overwrites=self.rules)
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(report['unexplained_cells'], 2)

    def test_explicit_clip_is_counted_but_out_of_bounds_is_not_implicitly_allowed(self):
        claim = [{'id': 'fixture:a', 'x': 0, 'clip': [0, 0, 0, 0]}]
        report = library.verify_stamp_audit(self.scene, claim, self.rows)
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(report['clipped_cells'], 1)
        outside = library.verify_stamp_audit(self.scene, [{'id': 'fixture:a', 'x': 3}], self.rows)
        self.assertEqual(outside['status'], 'FAIL')
        self.assertEqual(outside['stamps'][0]['unauthorized_clip'], 1)


class StrictVanillaTests(unittest.TestCase):
    def test_registry_rejects_unknown_blocks_and_missing_explicit_properties(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'invalid.schem'
            for value in ['minecraft:invented_wall', 'minecraft:diorite_wall', 'create:brass_block']:
                write_schematic(path, np.zeros((1, 1, 1), np.int32), [value])
                with self.assertRaisesRegex(ValueError, 'not strict vanilla'):
                    atlas.validate_vanilla(path)

    def test_registry_accepts_frozen_decorative_lower_door_and_explicit_wall(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'valid.schem'
            write_schematic(path, np.array([[[0, 1]]], np.int32),
                            [DOOR, WALL.replace('create:cut_calcite_wall', 'minecraft:diorite_wall')])
            self.assertEqual(atlas.validate_vanilla(path)['status'], 'PASS')


if __name__ == '__main__':
    unittest.main()
