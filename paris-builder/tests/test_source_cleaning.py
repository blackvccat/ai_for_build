"""Real failure modes: palette order and cleaning must not corrupt source evidence."""
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from survey_incoming import survey, verdict
from extract_details import state_grid, clean_cut, base_names, normalise_doors
from paris_builder.exporter import write_schematic
from paris_builder.schematic import load_schematic
from paris_builder.source_decomposition import crop, migrate_to_12111


class SourceCleaningTests(unittest.TestCase):
    def test_palette_zero_can_be_real_material_and_air_can_have_any_id(self):
        # Exporter sorts the palette: acacia_planks becomes 0 and air becomes 1.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.schem'
            volume = np.ones((3, 3, 3), dtype=np.int32)
            volume[1, 1, 1] = 0
            write_schematic(path, volume, ['minecraft:acacia_planks', 'minecraft:air'])
            data = load_schematic(path)
            self.assertEqual(data.air_ids.tolist(), [1])
            measured = survey(path)
            self.assertEqual(measured['nonair'], 1)
            self.assertEqual(measured['top_blocks'], [['minecraft:acacia_planks', 1]])
            self.assertEqual(len(measured['sha256_source']), 64)
            self.assertEqual(state_grid(data)[1, 1, 1], 'minecraft:acacia_planks')
            self.assertEqual(int((state_grid(data) == 'minecraft:air').sum()), 26)

    def test_cleaning_a_cut_cannot_change_source_or_another_overlapping_cut(self):
        lower = 'minecraft:iron_door[facing=north,half=lower,hinge=left,open=false,powered=false]'
        grid = np.full((2, 1, 1), lower, dtype=object)
        original = grid.copy()
        trimmed, _ = clean_cut(grid, base_names(grid), (0, 0, 0, 1, 0, 0), seal=False)
        changed, unpaired, originals = normalise_doors(trimmed)
        np.testing.assert_array_equal(grid, original)
        self.assertEqual(changed, 1)
        self.assertFalse(unpaired)
        self.assertEqual(originals, {lower: 2})

    def test_volume_fill_does_not_exclude_surface_techniques(self):
        row = {'envelope_whd': [20, 20, 20], 'nonair': 8000, 'fill_ratio': 1.0,
               'stateful_ratio': 0.2, 'modded_ratio': 0, 'block_entities': 0}
        accepted, notes = verdict(row)
        self.assertTrue(accepted)
        self.assertTrue(notes)

    def test_version_migration_preserves_special_states_and_logs_coordinates(self):
        old = 'minecraft:chain[axis=x,waterlogged=false]'
        door = 'minecraft:iron_door[facing=east,half=lower,hinge=right,open=false,powered=false]'
        original = np.array([[[old,door]]],dtype=object)
        cleaned, changes = migrate_to_12111(original,[10,20,30])
        self.assertEqual(cleaned[0,0,0], 'minecraft:iron_chain[axis=x,waterlogged=false]')
        self.assertEqual(cleaned[0,0,1],door)
        self.assertEqual(original[0,0,0],old)
        self.assertEqual(changes[0]['source_xyz'],[10,20,30])

    def test_quarantined_records_are_not_recommended_but_remain_addressable(self):
        from paris_builder.learning import KnowledgeIndex, record
        index=KnowledgeIndex.__new__(KnowledgeIndex)
        good=record('good','component','Good','',[])
        suspect=record('suspect','component','Suspect','',[],retrieval_eligible=False)
        index.records=[good,suspect]
        index.by_id={r['id']:r for r in index.records}
        index.reviews=lambda: {}
        result=index.query()
        self.assertEqual([r['id'] for r in result['items']],['good'])
        self.assertIn('suspect',index.by_id)

    def test_reference_page_rejects_paths_outside_its_library(self):
        from fastapi import HTTPException
        from paris_builder.learning_web import reference_decomposition_asset
        with self.assertRaises(HTTPException):
            reference_decomposition_asset('../../../../README.md')


if __name__ == '__main__':
    unittest.main()
