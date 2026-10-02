"""Source states must form visible, correctly rotated, surviving window motifs."""
import unittest

from paris_builder import design
from paris_builder.architecture import split_state, transform_state
from paris_builder.technique_library import load_detail


class CornerSourceStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = design.plan_for('corner_house', width=24, depth=30, storeys=6,
                                  detail_profile='reference_haussmann', bay_pitch=6,
                                  roof_height=9)
        cls.scene, cls.manifest = design.build(cls.plan, tier=3)

    def value(self, xyz):
        x, y, z = xyz
        return self.scene.palette[int(self.scene.volume[y, z, x])]

    def test_every_residential_street_window_has_all_three_source_motifs(self):
        audit = self.manifest['source_state_audit']
        windows = [(i, o) for i, o in enumerate(self.manifest['openings'])
                   if o['face'] in ('street_north', 'street_east') and o['floor'] > 0]
        self.assertEqual(len(windows), 35)
        for i, opening in windows:
            rows = [r for r in audit if r['opening_id'] == i]
            counts = {role: sum(r['role'] == role for r in rows)
                      for role in ('thin_door_window', 'single_arm_wall', 'shaped_stair')}
            self.assertEqual(counts, {'thin_door_window': opening['height'] * 2,
                                      'single_arm_wall': opening['height'] * 2,
                                      'shaped_stair': 4})
            self.assertTrue(all(r['face'] == opening['face'] for r in rows))
            self.assertTrue(all(r['survives'] and self.value(r['target_xyz']) == r['transformed_state']
                                for r in rows))

    def test_source_states_and_coordinates_rotate_together_on_both_streets(self):
        reads = {ident: load_detail(ident) for ident in ('v3:s3-window-bay', 'v3:street3-facade-4')}
        seen = set()
        for row in self.manifest['source_state_audit']:
            read = reads[row['source_id']]
            x, y, z = row['source_local_xyz']
            original = read.id_to_state[int(read.volume[y, z, x])]
            self.assertEqual(original, row['original_state'])
            self.assertEqual(row['turns'], 2 if row['face'] == 'street_north' else 3)
            self.assertEqual(transform_state(original, row['turns']), self.value(row['target_xyz']))
            seen.add((row['face'], row['role']))
        self.assertEqual(len(seen), 6)

    def test_special_properties_are_frozen_and_decorative_exemption_is_exact(self):
        leaves = {tuple(r['xyz']): r['state'] for r in self.manifest['decorative_doors']}
        for row in self.manifest['source_state_audit']:
            _, props = split_state(row['transformed_state'])
            if row['role'] == 'thin_door_window':
                self.assertEqual(props['half'], 'lower')
                self.assertEqual(leaves[tuple(row['target_xyz'])], row['transformed_state'])
                self.assertEqual(row['target_xyz'][2] if row['face'] == 'street_north'
                                 else row['target_xyz'][0], 7 if row['face'] == 'street_north' else 28)
            elif row['role'] == 'single_arm_wall':
                self.assertEqual(props['up'], 'false')
                self.assertEqual(sum(props[d] != 'none' for d in ('north', 'east', 'south', 'west')), 1)
            elif row['role'] == 'shaped_stair':
                self.assertEqual(props['half'], 'top')
        shapes = {split_state(r['transformed_state'])[1]['shape']
                  for r in self.manifest['source_state_audit'] if r['role'] == 'shaped_stair'}
        self.assertTrue({'inner_left', 'inner_right'} <= shapes)
        self.assertEqual(self.manifest['game_acceptance'], 'PENDING')

    def test_tier_three_adds_states_without_changing_accepted_structure(self):
        _, tier2 = design.build(self.plan, tier=2)
        self.assertEqual(tier2['structure'], self.manifest['structure'])
        self.assertEqual(tier2['openings'], self.manifest['openings'])
        self.assertFalse(tier2['source_state_audit'])
        self.assertFalse(tier2['decorative_doors'])


if __name__ == '__main__':
    unittest.main()
