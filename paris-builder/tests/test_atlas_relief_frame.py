"""The plain frame must contain relief geometry before source detail exists."""
from copy import deepcopy
import unittest

import numpy as np

from paris_builder.atlas_composition import composition_for
from paris_builder.atlas_street1_frame import (
    GLASS, PLINTH, ROOF, STONE, build_frame)
from paris_builder.design import plan_for


class AtlasReliefFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = plan_for('corner_house', seed=1901, width=46, depth=42,
                            detail_profile='atlas_street1', composition_profile='grouped_pavilions')
        cls.composition = composition_for(cls.plan, 6, 5)
        cls.scene, cls.manifest = build_frame(cls.plan, cls.composition, persist=False)
        cls.spec = cls.manifest['atlas_frame_spec']

    @classmethod
    def state(cls, point):
        x, y, z = point
        return cls.scene.palette[int(cls.scene.volume[y, z, x])]

    @staticmethod
    def point(side, axis, y, inward):
        return [axis, y, inward] if side == 'north' else [inward, y, axis]

    def test_frame_remains_procedural_four_materials_with_pure_shared_spec(self):
        self.assertEqual(set(self.scene.palette), {'minecraft:air', STONE, PLINTH, ROOF, GLASS})
        self.assertFalse(any('[' in value for value in self.scene.palette))
        self.assertEqual(self.manifest['stamps'], [])
        self.assertEqual(self.manifest['techniques'], [])
        self.assertNotIn('schematic', self.manifest)
        self.assertNotIn('independent_registry', self.manifest)
        original = deepcopy(self.composition)
        _, repeated = build_frame(self.plan, self.composition, persist=False)
        self.assertEqual(self.composition, original)
        self.assertEqual(repeated['atlas_frame_spec'], self.spec)
        self.assertEqual(self.scene.volume.shape, (52, 42, 45))

    def test_actual_pavilions_project_two_from_recessed_body_planes(self):
        for wing in ('north', 'west'):
            segments = [row for row in self.spec['wing_segments'] if row['wing'] == wing]
            recessed = next(row['wall_front'] for row in segments if row['projection'] == 0)
            for row in segments:
                axis = row['axis_interval'][0] + 3
                front = row['wall_front']
                self.assertEqual(self.state(self.point(wing, axis, 11, front)), STONE)
                if row['projection']:
                    self.assertEqual(recessed - front, 2)
                    self.assertEqual(self.state(self.point(wing, axis, 11, front - 1)), 'minecraft:air')

    def test_base_balcony_and_three_cornice_courses_are_real_voxels(self):
        for row in self.spec['wing_segments']:
            wing, front = row['wing'], row['wall_front']
            axis = row['axis_interval'][0] + 3
            self.assertEqual(self.state(self.point(wing, axis, 2, front - 1)), STONE)
            self.assertEqual(self.state(self.point(wing, axis, 0, front - 1)), PLINTH)
            self.assertEqual(self.state(self.point(wing, axis, 12, front - 1)), STONE)
            self.assertEqual(self.state(self.point(wing, axis, 27, front - 1)), STONE)
            for y, projection in ((26, 0), (27, 1), (28, 2)):
                self.assertEqual(self.state(self.point(wing, axis, y, front - projection)), STONE)
                self.assertEqual(self.state(self.point(wing, axis, y, front - projection - 1)), 'minecraft:air')

    def test_each_plain_window_is_recessed_two_with_a_clear_outward_ray(self):
        heights = {}
        for opening in self.spec['openings']:
            self.assertEqual(opening['reveal_depth'], 2)
            normal = 2 if opening['wing'] == 'north' else 0
            for point in opening['glass_cells_xyz']:
                self.assertEqual(self.state(point), GLASS)
                self.assertEqual(point[normal] - opening['facade_front'], 2)
                for inward in range(point[normal]):
                    outside = list(point)
                    outside[normal] = inward
                    self.assertEqual(self.state(outside), 'minecraft:air')
            if opening['bay_index'] == 1 and opening['wing'] == 'north':
                heights[opening['role']] = len({point[1] for point in opening['glass_cells_xyz']})
        self.assertEqual([heights[role] for role in ('standard', 'noble_lower', 'noble_upper')], [3, 4, 3])
        self.assertEqual(heights['shop_placeholder'], 5)

    def test_dormer_houses_have_cheeks_and_caps_in_front_of_roof_contact(self):
        houses = self.spec['relief_geometry']['dormer_houses']
        self.assertEqual(len(houses), 18)
        for house in houses:
            wing = house['wing']
            normal = 2 if wing == 'north' else 0
            tangent = 0 if normal == 2 else 2
            cap = house['roof_cap_bboxes_xyz_half_open'][0]
            # The visible front roof overhang and both front cheeks survive
            # construction of the other dormer row and the orthogonal wing.
            cap_point = cap[:3]
            self.assertEqual(self.state(cap_point), ROOF)
            self.assertLess(cap[normal], house['front_plane'])
            for cheek in house['cheek_bboxes_xyz_half_open']:
                point = cheek[:3]
                point[1] += 2
                self.assertEqual(self.state(point), STONE)
            self.assertGreater(house['slope_contact_bbox_xyz_half_open'][normal], house['front_plane'])
            self.assertGreater(cap[tangent + 3] - cap[tangent], 4)

    def test_source_skin_targets_stay_explicit_and_corner_is_third_volume(self):
        native = next(row for row in self.spec['source_openings']
                      if row['wing'] == 'north' and row['role'] == 'standard' and row['bay_index'] == 1)
        plain = next(row for row in self.spec['openings']
                     if row['wing'] == 'north' and row['role'] == 'standard' and row['bay_index'] == 1)
        self.assertNotEqual(native['glass_cells_xyz'], plain['glass_cells_xyz'])
        self.assertEqual(len(native['glass_cells_xyz']), 8)
        # Shaft body extends outward on both streets. Its circular footprint
        # varies with the other axis instead of merely intersecting two boxes.
        stone_id = self.scene.palette.index(STONE)
        shaft = np.argwhere(self.scene.volume[11] == stone_id)
        self.assertLess(int(shaft[:, 0].min()), min(row['wall_front'] for row in self.spec['wing_segments']))
        self.assertLess(int(shaft[:, 1].min()), min(row['wall_front'] for row in self.spec['wing_segments']))
        self.assertEqual(self.spec['corner']['cap_top_y'], 46)
        self.assertEqual(self.state([12, 46, 14]), ROOF)


if __name__ == '__main__':
    unittest.main()
