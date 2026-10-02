"""Export geometry distinguishes slope defects from local roof attachments."""
from pathlib import Path
import tempfile
import unittest

import numpy as np

from paris_builder.exporter import write_schematic
from paris_builder.facade_section import measure as measure_section
from paris_builder.roof_conformance import classify_profile, measure


class RoofConformanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'candidate.schem'
        # Nonzero air ids must not turn holes into evidence of a solid roof.
        self.palette = ['minecraft:sandstone', 'minecraft:air', 'minecraft:deepslate_tiles',
                        'minecraft:spruce_planks', 'minecraft:polished_deepslate', 'minecraft:glass']
        self.profile = [0, 2, 4, 6, 7, 7, 8, 8, 8, 9, 9, 9, 10]
        self.make_roof(self.profile)

    def make_roof(self, profile, solid=False):
        self.v = np.ones((34, 35, 29), dtype=np.int32)
        self.v[0, 2:33, 2:27] = 0
        for y in (1, 5, 9):
            self.v[y, 2:33, 2:27] = 3
        for z in range(2, 33):
            for x in range(2, 27):
                distance = min(x-2, 26-x, z-2, 32-z)
                high = 10+profile[distance]
                self.v[(10 if solid else max(10, high-1)):high+1, z, x] = 2

    def report(self, **kwargs):
        write_schematic(self.path, self.v, self.palette)
        return measure(self.path, **kwargs)

    def test_valid_mansard_has_measured_break_and_narrow_transverse_ridge(self):
        report = self.report(plan={'roof_height': 100, 'roof_break': 100, 'roof_ridge_cells': 100})
        self.assertEqual(report['checks'][0]['status'], 'pass')
        self.assertEqual(report['ridge']['transverse_axis'], 'x')
        self.assertEqual(report['ridge']['width_cells'], 1)
        for face in report['faces'].values():
            self.assertGreater(face['lower_slope'], 1.25)
            self.assertLess(face['upper_slope'], .75)
            self.assertEqual(face['classification'], 'steep_lower_shallow_upper')
        for z, row in enumerate(report['surface']['height_y_z_x'], start=2):
            for x, height in enumerate(row, start=2):
                if height is not None:
                    self.assertEqual(self.v[height, z, x], 2)

    def test_linear_roof_failure_describes_wrong_shape(self):
        self.make_roof(list(range(13)))
        report = self.report()
        check = report['checks'][0]
        self.assertEqual(check['status'], 'fail')
        self.assertIn('Required mansard geometry is absent', check['reason'])
        self.assertIn('slope_contrast', check['reason'])
        self.assertNotIn('cannot be verified', check['reason'])
        self.assertEqual(report['faces']['west']['classification'], 'linear_or_insufficient_slope_break')

    def test_broad_flat_cap_fails_even_after_steep_lower_slope(self):
        self.make_roof([0, 2, 4, 6, 7, 8, 8, 8, 8, 8, 8, 8, 8])
        report = self.report()
        self.assertEqual(report['checks'][0]['status'], 'fail')
        self.assertGreater(report['ridge']['width_cells'], 3)
        self.assertIn('ridge/plateau spans', report['checks'][0]['reason'])

    def test_chimneys_and_dormers_do_not_change_main_roof_verdict(self):
        baseline = self.report()
        # Same roof material, so a material-name shortcut cannot remove spikes.
        for x, z in ((10, 16), (20, 18), (14, 10)):
            roof_y = 10+self.profile[min(x-2, 26-x, z-2, 32-z)]
            self.v[roof_y+1:roof_y+6, z, x] = 2
        # A bounded dormer has its own raised roof and cuts two actual holes.
        for z in range(8, 11):
            for x in range(7, 9):
                roof_y = 10+self.profile[min(x-2, 26-x, z-2, 32-z)]
                self.v[roof_y+3, z, x] = 2
        self.v[:, 24, 9] = 1
        self.v[0, 24, 9] = 0
        for y in (1, 5, 9):
            self.v[y, 24, 9] = 3
        changed = self.report()
        self.assertEqual(changed['checks'][0]['status'], 'pass')
        self.assertNotEqual(baseline['source']['sha256'], changed['source']['sha256'])
        self.assertGreaterEqual(len(changed['surface']['elevated_columns']), 8)
        self.assertIn([9, 24], changed['surface']['missing_columns_xz'])
        self.assertEqual(changed['faces']['west']['lower_slope'], baseline['faces']['west']['lower_slope'])
        self.assertEqual(changed['ridge']['width_cells'], baseline['ridge']['width_cells'])

    def test_broad_competing_surface_cannot_be_discarded_as_an_appendage(self):
        self.make_roof(self.profile, solid=True)
        for z in range(8, 27):
            for x in range(4, 9):
                high = 10+self.profile[min(x-2, 26-x, z-2, 32-z)]
                self.v[high+1:high+5, z, x] = 2
        report = self.report()
        self.assertEqual(report['checks'][0]['status'], 'unsupported')
        self.assertIn('broad competing roof volume', report['checks'][0]['reason'])

    def test_cached_section_must_match_exact_export(self):
        write_schematic(self.path, self.v, self.palette)
        section = measure_section(self.path)
        self.v[26, 15, 10] = 2
        write_schematic(self.path, self.v, self.palette)
        with self.assertRaisesRegex(ValueError, 'SHA-256 differs'):
            measure(self.path, section=section)

    def test_wrong_material_and_small_roof_are_unsupported(self):
        self.palette[2] = 'minecraft:red_wool'
        self.assertEqual(self.report()['checks'][0]['status'], 'unsupported')
        self.assertEqual(classify_profile([0, 2, 4, 5])['status'], 'unsupported')

    def test_an_entire_bad_face_cannot_borrow_another_faces_pass(self):
        # Above-shell defects too broad to be local appendages are never hidden
        # by the other three faces' consensus.
        self.make_roof(self.profile, solid=True)
        for z in range(6, 29):
            for x in range(3, 9):
                high = 10+self.profile[min(x-2, 26-x, z-2, 32-z)]
                self.v[high+1:high+4, z, x] = 2
        report = self.report()
        self.assertNotEqual(report['checks'][0]['status'], 'pass')


if __name__ == '__main__':
    unittest.main()
