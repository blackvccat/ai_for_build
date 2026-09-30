import tempfile
import unittest
from pathlib import Path

import numpy as np

from paris_builder.exporter import encode_varints, write_schematic
from paris_builder.schematic import decode_varints, load_schematic


class ExporterTests(unittest.TestCase):
    def test_varint_boundaries(self):
        values = [0, 1, 127, 128, 255, 16383, 16384, 2147483647]
        self.assertEqual(decode_varints(encode_varints(values)).tolist(), values)
        with self.assertRaises(ValueError):
            encode_varints([-1])

    def test_asymmetric_axis_roundtrip_and_byte_determinism(self):
        volume = np.zeros((5, 4, 7), dtype=np.int32)
        volume[4, 2, 6] = 1
        volume[1, 3, 2] = 2
        palette = ["minecraft:air", "minecraft:stone", "minecraft:quartz_block"]
        with tempfile.TemporaryDirectory() as folder:
            first, second = Path(folder) / "a.schem", Path(folder) / "b.schem"
            write_schematic(first, volume, palette)
            write_schematic(second, volume, palette)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            loaded = load_schematic(first)
            self.assertEqual((loaded.width, loaded.height, loaded.length), (7, 5, 4))
            self.assertEqual(loaded.id_to_state[loaded.volume[4, 2, 6]], "minecraft:stone")
            self.assertEqual(loaded.id_to_state[loaded.volume[1, 3, 2]], "minecraft:quartz_block")
            self.assertEqual(loaded.validation()["status"], "PASS")

    def test_unused_palette_order_does_not_change_bytes(self):
        first_volume = np.asarray([[[0, 1]]], dtype=np.int32)
        second_volume = np.asarray([[[2, 0]]], dtype=np.int32)
        with tempfile.TemporaryDirectory() as folder:
            a, b = Path(folder) / "a.schem", Path(folder) / "b.schem"
            write_schematic(a, first_volume, ["minecraft:air", "minecraft:stone"])
            write_schematic(b, second_volume, ["minecraft:stone", "minecraft:dirt", "minecraft:air"])
            self.assertEqual(a.read_bytes(), b.read_bytes())


if __name__ == "__main__":
    unittest.main()
