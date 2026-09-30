import unittest

import numpy as np

from paris_builder.schematic import decode_varints, orthographic_surface_mask


class VarIntTests(unittest.TestCase):
    def test_decodes_single_and_multi_byte_values(self):
        encoded = [0x00, 0x01, 0x7F, 0x80, 0x01, 0xAC, 0x02]
        self.assertEqual(decode_varints(encoded).tolist(), [0, 1, 127, 128, 300])

    def test_rejects_incomplete_value(self):
        with self.assertRaises(ValueError):
            decode_varints([0x80])


class SurfaceTests(unittest.TestCase):
    def test_solid_cube_surface_excludes_center(self):
        occupied = np.ones((3, 3, 3), dtype=bool)
        surface = orthographic_surface_mask(occupied)
        self.assertEqual(int(surface.sum()), 26)
        self.assertFalse(bool(surface[1, 1, 1]))

    def test_single_block_is_visible(self):
        occupied = np.zeros((3, 3, 3), dtype=bool)
        occupied[1, 1, 1] = True
        surface = orthographic_surface_mask(occupied)
        self.assertEqual(int(surface.sum()), 1)
        self.assertTrue(bool(surface[1, 1, 1]))


if __name__ == "__main__":
    unittest.main()
