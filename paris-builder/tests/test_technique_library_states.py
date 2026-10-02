"""Stamp and audit must retain real stair states while skipping genuine air."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np

from paris_builder.architecture import Scene
from paris_builder import technique_library as library


class TechniqueLibraryStateTests(unittest.TestCase):
    def test_real_source_window_stairs_are_stamped_and_audited(self):
        ident = 'v3:s3-window-bay'
        source = library.load_detail(ident)
        scene = Scene(12, 12, 12)
        count = library.stamp(scene, ident, 2, 2, 2)
        self.assertEqual(count, sum(int((source.volume == i).sum())
                                   for i, value in enumerate(source.id_to_state)
                                   if not library._is_air_state(value)))
        stairs = []
        for y, z, x in np.ndindex(source.volume.shape):
            value = source.id_to_state[int(source.volume[y, z, x])]
            if '_stairs[' in value:
                self.assertEqual(scene.palette[int(scene.volume[y + 2, z + 2, x + 2])], value)
                stairs.append((x + 2, y + 2, z + 2))
        self.assertEqual(len(stairs), 4)
        audit = [{'id': ident, 'x': 2, 'y': 2, 'z': 2}]
        self.assertEqual(library.verify_stamp_audit(scene, audit)['status'], 'PASS')
        scene.put(*stairs[0], 'minecraft:air')
        broken = library.verify_stamp_audit(scene, audit)
        self.assertEqual(broken['status'], 'FAIL')
        self.assertEqual(broken['matched_cells'], count - 1)

    def test_nonzero_air_and_air_variants_do_not_hide_stairs(self):
        states = ['minecraft:sandstone_stairs[facing=north,half=top,shape=inner_left,waterlogged=false]',
                  'minecraft:air', 'minecraft:cave_air', 'minecraft:void_air']
        read = SimpleNamespace(volume=np.array([[[0, 1, 2, 3]]]), id_to_state=states,
                               air_ids=[])
        scene = Scene(6, 3, 3)
        rows = [{'id': 'fixture:stairs', 'path': 'fixture.schem'}]
        with patch.object(library, 'load_detail', return_value=read):
            self.assertEqual(library.stamp(scene, 'fixture:stairs', 1, 1, 1), 1)
            self.assertEqual(scene.palette[int(scene.volume[1, 1, 1])], states[0])
            report = library.verify_stamp_audit(scene, [{'id': 'fixture:stairs', 'x': 1, 'y': 1, 'z': 1}], rows)
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(report['matched_cells'], 1)


if __name__ == '__main__':
    unittest.main()
