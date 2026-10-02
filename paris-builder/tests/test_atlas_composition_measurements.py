"""Final-schematic corruption regressions for the independent composition receipt.

Read one persisted scene once and mutate a private volume copy for each test.
No assembly, registry, rendering, source-library writes or artifact rewrites run.
The archived fixture is intentionally a geometric reference, not a visually
approved building: passing these checks must not imply composition acceptance.
"""
from copy import copy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import unittest

from paris_builder.schematic import load_schematic


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'atlas_composition_measurements', ROOT / 'tools' / 'verify_atlas_composition.py')
measure = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(measure)


class AtlasCompositionMeasurementCorruptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        candidates = [ROOT / 'runs' / name for name in
                      ('ATLAS-COMPOSE-PROBE', 'ATLAS-PLAN-P2-v0.1')]
        cls.fixture_dir = next((run for run in candidates
                        if all((run / name).is_file() for name in
                               ('ATLAS-HOUSE.schem', 'composition.json', 'assembly.json'))), None)
        if cls.fixture_dir is None:
            raise unittest.SkipTest('A persisted composed scene is required; no new build is run by these tests.')
        cls.source_read = load_schematic(cls.fixture_dir / 'ATLAS-HOUSE.schem')
        cls.composition = json.loads((cls.fixture_dir / 'composition.json').read_text(encoding='utf-8'))
        cls.rows = json.loads((cls.fixture_dir / 'assembly.json').read_text(encoding='utf-8'))['stamps']
        cls.source_volume_sha256 = sha256(cls.source_read.volume.tobytes()).hexdigest()

    def setUp(self):
        self.baseline = measure.Measurement(self.source_read, self.rows)
        read = copy(self.source_read)
        read.volume = self.source_read.volume.copy()
        read.block_ids = read.volume.reshape(-1)
        self.changed = measure.Measurement(read, self.rows)

    def tearDown(self):
        self.assertEqual(sha256(self.source_read.volume.tobytes()).hexdigest(), self.source_volume_sha256,
                         'Corruption tests must never mutate the persisted-scene baseline.')

    def erase(self, points):
        self.assertTrue(points, 'A corruption test must actually remove an observed feature.')
        for x, y, z in points:
            self.changed.volume[y, z, x] = self.changed.air_ids[0]

    def assert_predicate_failure(self, function, predicate_id, *, crown_index=None):
        baseline = function(self.baseline, self.composition)
        changed = function(self.changed, self.composition)
        if crown_index is not None:
            baseline, changed = baseline[crown_index], changed[crown_index]
        self.assertEqual(baseline['id'], predicate_id)
        self.assertEqual(baseline['status'], measure.PASS,
                         'The intact fixture must pass this specific predicate before corruption.')
        self.assertEqual(changed['id'], predicate_id)
        self.assertEqual(changed['status'], measure.FAIL,
                         'The corresponding individual predicate must catch the corruption.')
        return changed

    def test_missing_one_chimney_mouth_fails_complete_cluster_predicate(self):
        row = self.changed.rows_for('chimney-north')[0]
        mouths = self.changed.points(measure._box(row), {'minecraft:flower_pot'})
        self.assertEqual(len(mouths), 5)
        self.erase([mouths[0]])
        result = self.assert_predicate_failure(measure._chimneys, 'chimney_complete_focus_clusters')
        self.assertEqual(len(result['evidence'][0]['actual_mouths']), 4)

    def test_missing_one_planter_stem_fails_noble_accent_predicate(self):
        row = self.changed.rows_for('plant-noble-north')[0]
        stems = self.changed.points(measure._box(row), {'minecraft:attached_pumpkin_stem'})
        self.assertEqual(len(stems), 2)
        self.erase([stems[0]])
        result = self.assert_predicate_failure(measure._plants, 'noble_source_accent_retention')
        self.assertEqual(len(result['evidence'][0]['actual_stem_cells']), 1)

    def test_missing_pavilion_front_leaves_fails_actual_projection_predicate(self):
        target = self.composition['wings']['north']['focal_bay']
        row = self.changed.rows_for('bay-noble-north', 0)[target]
        doors = self.changed.points(measure._box(row), {'minecraft:iron_door'})
        self.assertTrue(doors)
        front = min(point[2] for point in doors)
        self.erase([point for point in doors if point[2] == front])
        result = self.assert_predicate_failure(measure._window_planes, 'wing_window_projection')
        observation = result['evidence'][0]['bays'][target]
        self.assertNotEqual(observation['actual_projection_from_recess'], observation['target_projection'])

    def test_missing_dark_cheek_fails_dormer_grade_predicate(self):
        row = self.changed.rows_for('dormer-pavilion-north')[0]
        doors = self.changed.points(measure._box(row), {'minecraft:iron_door'})
        middle_y = row['anchor'][1] + 3
        samples = [point for point in doors if point[1] == middle_y]
        self.assertTrue(samples)
        front = min(point[2] for point in samples)
        cross = [point[0] for point in samples if point[2] == front]
        cheek = [min(cross) - 1, middle_y, front]
        self.assertIn(self.changed.state(*cheek), measure.DARK_CHEEKS)
        self.erase([cheek])
        self.assert_predicate_failure(measure._dormer_cheeks, 'dormer_grade_echo')

    def test_missing_highest_crown_ornaments_fails_roof_height_predicate(self):
        row = self.changed.rows_for('turret-finial')[0]
        points = self.changed.points(measure._box(row))
        self.assertTrue(points)
        highest = max(point[1] for point in points)
        self.erase([point for point in points if point[1] == highest])
        result = self.assert_predicate_failure(measure._crown, 'corner_crown_above_ridge', crown_index=0)
        self.assertLessEqual(result['evidence']['actual_crown_top_y'],
                             result['evidence']['actual_wing_roof_top_y'])

    def test_missing_all_roof_contacts_fails_platform_contact_predicate(self):
        row = self.changed.rows_for('turret-finial')[0]
        box = measure._box(row)
        below = [box[0], box[1] - 1, box[2], box[3], box[1], box[5]]
        contacts = self.changed.points(below, measure.ROOF_MINERALS)
        self.erase(contacts)
        result = self.assert_predicate_failure(measure._crown, 'corner_crown_platform_contact', crown_index=1)
        self.assertEqual(result['evidence']['actual_roof_contact_cells'], 0)


if __name__ == '__main__':
    unittest.main()
