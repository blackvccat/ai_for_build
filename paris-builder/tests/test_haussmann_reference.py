"""Source-state preservation and actual circulation, not appearance acceptance."""
import tempfile
import unittest
from pathlib import Path

from paris_builder import design
from paris_builder.exporter import write_schematic
from paris_builder.geometry import inspect_geometry
from paris_builder.schematic import load_schematic


class ReferenceHouseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = design.plan_for('street_house', width=27, depth=28, storeys=6,
            detail_profile='reference_haussmann', bay_pitch=5, entrance_fraction=.5, roof_height=7)
        cls.scene, cls.manifest = design.build(cls.plan)

    def value(self, x, y, z):
        return self.scene.palette[self.scene.volume[y, z, x]]

    def test_framework_roof_has_measured_steep_lower_and_shallow_upper_slopes(self):
        for height in range(5, 10):
            plan = design.plan_for('street_house', width=23, depth=24, storeys=6,
                detail_profile='reference_haussmann', roof_height=height)
            scene, manifest = design.build(plan, tier=0)
            section = manifest['structure']['roof_section']
            rises = section['rises_from_eave']; knee = section['slope_break_distance']
            lower = (rises[knee] - rises[0]) / knee
            upper = (max(rises) - rises[knee]) / (11 - knee)
            self.assertGreater(lower, upper)
            self.assertGreater(lower, 1)
            self.assertLess(upper, 1)
            self.assertEqual(max(rises), height)
            self.assertEqual(rises, rises[::-1])
            for offset, rise in enumerate(rises):
                state = scene.palette[scene.volume[manifest['structure']['top'] + rise, 6 + offset, 12]]
                self.assertEqual(state, 'minecraft:deepslate_tiles')

    def test_roof_is_hollow_and_stairs_have_headroom(self):
        m = self.manifest
        self.assertEqual(len(m['bay_x']), 5)
        for x, y, z in m['stair_cells']:
            self.assertEqual(self.value(x, y + 1, z), 'minecraft:air')
            self.assertEqual(self.value(x, y + 2, z), 'minecraft:air')
        top = m['structure']['top']
        self.assertEqual(self.value(12, top + 2, 20), 'minecraft:air')

    def test_party_walls_blind_and_residence_separate_from_cafe(self):
        m = self.manifest
        self.assertTrue(all(w['openings'] == 0 for w in m['walls'] if w['role'] == 'party'))
        ground = [o for o in m['openings'] if o['floor'] == 0 and o['face'] == 'street']
        self.assertEqual(sum(o['kind'] == 'door' for o in ground), 1)
        self.assertEqual(sum(o['kind'] == 'cafe_door' for o in ground), 1)
        for o in ground:
            if o['kind'].endswith('door'):
                self.assertIn('dark_oak_door', self.value(o['x'], o['y'], o['z']))

    def test_shops_have_wide_glazing_and_residential_windows_remain_independent(self):
        shops = [o for o in self.manifest['openings'] if o['kind'] == 'shop']
        self.assertTrue(shops)
        for o in shops:
            self.assertEqual(o['width'], 4)
            self.assertEqual(o['height'], 6)
            self.assertEqual(self.value(o['x'], o['y'], o['z']), 'minecraft:polished_andesite')
            self.assertEqual(self.value(o['x'], o['y'] + o['height'], o['z']), 'minecraft:dark_oak_planks')
            self.assertIn('stained_glass', self.value(o['x'], o['y'] + 1, o['z'] + 1))
        attic = [o for o in self.manifest['openings'] if o['floor'] == 5]
        self.assertTrue(all(o['height'] == 3 for o in attic))

    def test_low_roof_keeps_slopes_and_dormers_above_eave(self):
        plan = design.plan_for('street_house', width=23, depth=24, storeys=6,
            detail_profile='reference_haussmann', bay_pitch=5, roof_height=5)
        scene, manifest = design.build(plan, tier=0)
        top = manifest['structure']['top']
        def value(x, y, z):
            return scene.palette[scene.volume[y, z, x]]
        # At the unpierced party edge the crown cannot become a plateau at distance 2.
        self.assertEqual(value(6, top + 5, 8), 'minecraft:air')
        self.assertEqual(value(6, top + 5, 17), 'minecraft:smooth_sandstone')
        bx = manifest['bay_x'][0]
        self.assertIn('stained_glass', value(bx, top + 2, 7))
        self.assertEqual(value(bx, top + 4, 7), 'minecraft:deepslate_tiles')

    def test_explicit_decorative_exemption_does_not_hide_broken_functional_doors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'house.schem'
            write_schematic(path, self.scene.volume, self.scene.palette)
            schem = load_schematic(path)
            self.assertEqual(inspect_geometry(schem)['status'], 'FAIL')
            report = inspect_geometry(schem, self.manifest['decorative_doors'])
            self.assertEqual(report['status'], 'PASS')
            door = next(o for o in self.manifest['openings'] if o['kind'] == 'door')
            schem.volume[door['y'] + 1, door['z'], door['x']] = schem.id_to_state.index('minecraft:air')
            self.assertEqual(inspect_geometry(schem, self.manifest['decorative_doors'])['status'], 'FAIL')

    def test_source_door_states_are_preserved_and_tier_zero_has_no_dressing(self):
        self.assertTrue(self.manifest['decorative_doors'])
        for cell in self.manifest['decorative_doors']:
            self.assertIn('half=lower', cell['state'])
            self.assertEqual(self.value(*cell['xyz']), cell['state'])
        _, manifest = design.build(self.plan, tier=0)
        self.assertFalse(manifest['decorative_doors'])
        self.assertEqual(manifest['techniques'], {})


if __name__ == '__main__':
    unittest.main()
