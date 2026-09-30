import json
import unittest
from pathlib import Path
import numpy as np
from paris_builder.retrieval import ComponentIndex, visual_descriptor

ROOT = Path(__file__).resolve().parents[1]


class RetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = ComponentIndex(ROOT / 'knowledge/retrieval')

    def test_all_production_components_preserve_evidence(self):
        catalog = json.loads((ROOT / 'knowledge/library-v1/catalog.json').read_text(encoding="utf-8"))
        originals = {e['component_id']: e for e in catalog['windows'] + catalog['recipes']}
        self.assertEqual(len(self.index.records), 178)
        for r in self.index.records:
            self.assertEqual(r['evidence'], originals[r['id']])

    def test_real_semantic_vectors(self):
        self.assertEqual(self.index.semantic.shape, (178, 384))
        np.testing.assert_allclose(np.linalg.norm(self.index.semantic, axis=1), 1, atol=1e-5)
        results = self.index.query('屋顶排放烟气的烟囱', limit=3)
        self.assertEqual(results[0]['family'], 'chimney')
        self.assertEqual(self.index.query('入口门廊')[0]['family'], 'portal')

    def test_filters_are_hard_constraints(self):
        results = self.index.query('薄窗套', family='window_assembly', max_width=3, max_depth=4)
        self.assertTrue(results)
        self.assertTrue(all(r['family'] == 'window_assembly' and r['dimensions'][0] <= 3
                            and r['dimensions'][2] <= 4 for r in results))
        self.assertEqual(self.index.query('窗', game_status='PASS'), [])

    def test_deterministic_and_explicit_unknown(self):
        a = self.index.query('窗户薄窗扇', family='shutter')
        b = self.index.query('窗户薄窗扇', family='shutter')
        self.assertEqual(a, b)
        self.assertTrue(all(r['game_status'] == 'NOT_RUN' for r in a))
        with self.assertRaises(ValueError): self.index.query(' ')

    def test_geometry_and_visual_are_separate_signals(self):
        record = self.index.records[0]
        path = ROOT / record['card']
        a = self.index.query('拱顶', family='arch', dimensions=[3, 3, 2], reference_image=path)
        self.assertIn('geometry', a[0]['scores'])
        self.assertIn('visual_statistics', a[0]['scores'])
        self.assertAlmostEqual(float(visual_descriptor(path) @ visual_descriptor(path)), 1, places=5)


if __name__ == '__main__': unittest.main()
