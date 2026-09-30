import json
import tempfile
import unittest
from pathlib import Path

from paris_builder import workflow as w
from paris_builder.design_contract import validate_concept
from paris_builder.executor import retrieval_payload, view_bundle


def valid_concept():
    return {'massing_seed': 1, 'style_id': 'paris_haussmann_v0.1', 'width': 64, 'depth': 48,
            'chamfer': 8, 'court_width': 22, 'court_depth': 24, 'storeys': 5, 'bay_pitch': 6,
            'roof_height': 10, 'entrance_fraction': 0.35, 'footprint_type': 'l_plan',
            'roof_profile': 'steep_lower_shallow_crown', 'facade_seed': 2, 'detail_seed': 3}


class ExecutorTests(unittest.TestCase):
    def test_view_bundle_maps_renderer_names_to_protocol(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            render = {}
            for key in ('front', 'back', 'left', 'right', 'top', 'axonometric_front', 'axonometric_back'):
                render[key] = root / (key + '.png')
            for degrees in range(0, 360, 45):
                render[f'orbit_street_{degrees:03d}'] = root / f'street_{degrees:03d}.png'
                render[f'orbit_high_{degrees:03d}'] = root / f'high_{degrees:03d}.png'
            for path in render.values():
                path.write_bytes(b'png')
            bundle = view_bundle(render)
            self.assertEqual(set(bundle), set(w.VIEWS))
            self.assertTrue(bundle['orbit_low_000']['path'].endswith('street_000.png'))
            self.assertTrue(all(len(v['sha256']) == 64 for v in bundle.values()))

    def test_retrieval_payload_separates_placeable_from_source_studies(self):
        result = {'id': 'window-source-38', 'family': 'window_assembly', 'dimensions': [4, 3, 5],
                  'score': 0.69, 'scores': {'semantic': 0.69}, 'game_status': 'NOT_RUN',
                  'evidence': {'annotation': {'update_policy': 'UNTESTED', 'outside': 'north/-z'}, 'evidence': []},
                  'explanation': 'window'}
        payload = retrieval_payload([result])
        self.assertFalse(payload[0]['placeable'])
        result['id'] = 'arch-v1'; result['family'] = 'arch'
        self.assertTrue(retrieval_payload([result])[0]['placeable'])

    def test_component_policy_rejects_unplaceable_and_bad_shape(self):
        concept = valid_concept()
        # A study family the alias table does not know must still be rejected.
        concept['component_policy'] = {'primary_street': {'roof_magic': {'variant': 0, 'reason': 'x', 'evidence_refs': ['a']}}}
        with self.assertRaisesRegex(ValueError, 'not placeable'):
            validate_concept(concept)
        concept['component_policy'] = {'primary_street': {'variant': 0, 'reason': 'x', 'evidence_refs': ['a']}}
        with self.assertRaisesRegex(ValueError, 'Invalid component selection'):
            validate_concept(concept)
        concept['component_policy'] = {'primary_street': {'arch': {'variant': 0, 'reason': 'x', 'evidence_refs': ['arch-v1']}}}
        self.assertEqual(validate_concept(concept), concept)

    def test_study_window_family_is_substituted_and_recorded(self):
        concept = valid_concept()
        concept['component_policy'] = {'primary_street': {'window_assembly': {'variant': 0, 'reason': 'x', 'evidence_refs': ['a']}}}
        validate_concept(concept)
        self.assertIn('window_surround', concept['component_policy']['primary_street'])

    def test_contract_keeps_design_limits(self):
        concept = valid_concept(); concept['storeys'] = 9
        with self.assertRaises(ValueError):
            validate_concept(concept)
        concept = valid_concept(); concept['court_width'] = 60
        with self.assertRaises(ValueError):
            validate_concept(concept)


if __name__ == '__main__':
    unittest.main()
