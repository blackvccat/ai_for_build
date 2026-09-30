import json
from pathlib import Path
import unittest

from paris_builder.learning_workflow import (
    build_massing_volume,
    concept_difference,
    generate_massing_concept,
)


ROOT = Path(__file__).resolve().parents[1]
STYLE = json.loads((ROOT / "knowledge/styles/paris_haussmann_v0.1.json").read_text(encoding="utf-8"))


class LearningWorkflowTests(unittest.TestCase):
    def test_seed_is_repeatable_and_detail_is_locked(self):
        first = generate_massing_concept(STYLE, 1103)
        second = generate_massing_concept(STYLE, 1103)
        self.assertEqual(first, second)
        self.assertEqual(first.stage, "MASSING_ONLY")
        self.assertEqual(first.detail_status, "PROHIBITED_UNTIL_MASSING_GATE_PASS")
        self.assertEqual(set(first.face_roles), {"north", "south", "west", "east", "top"})

    def test_seeded_candidates_change_architectural_axes(self):
        concepts = [generate_massing_concept(STYLE, seed) for seed in (1103, 2207, 3319)]
        for index, left in enumerate(concepts):
            for right in concepts[index + 1:]:
                self.assertGreaterEqual(concept_difference(left, right)["count"], 3)

    def test_massing_palette_cannot_smuggle_in_detail_blocks(self):
        concept = generate_massing_concept(STYLE, 2207)
        volume, palette, metadata = build_massing_volume(concept)
        self.assertEqual(volume.ndim, 3)
        self.assertTrue(volume.any())
        self.assertEqual(len(palette), 4)
        self.assertTrue(metadata["zone_palette_only"])
        self.assertFalse(any(token in state for state in palette
                             for token in ("stairs", "wall[", "pane", "trapdoor", "fence")))
        self.assertIn("bay and storey void rhythm", metadata["framework_included"])


if __name__ == "__main__":
    unittest.main()
