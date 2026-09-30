import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from paris_builder import generator_repair as repair, atelier_workflow as a, workflow as w, operations, design
from paris_builder.learning import read_json
from paris_builder.schematic import load_schematic
from paris_builder.operations import write_json


class GeneratorRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.base = repair.sources({})
        self.plan = {'form': 'corner_house', 'scheme': 'haussmann_apartment', 'width': 28,
                     'depth': 24, 'storeys': 6, 'seed': 1900}
        self.edit = {'file': 'design.py', 'before': '    span = max(3, width // 5)',
                     'after': '    span = max(3, width // 6)'}

    def test_patch_is_task_local_hash_bound_and_loadable(self):
        version = repair.create_version(self.folder, self.base, [self.edit], 'change dormer rhythm')
        self.assertNotEqual(repair.version_files(version)['design.py'], self.base['design.py'])
        self.assertEqual(repair.sources({})['design.py'], self.base['design.py'])
        (Path(version['path']) / 'design.py').write_text('changed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '版本文件'):
            repair.version_files(version)

    def test_paths_ambiguous_edits_and_noops_are_rejected(self):
        for edit in ({**self.edit, 'file': '../providers.py'}, {**self.edit, 'before': ' '},
                     {**self.edit, 'after': self.edit['before']}):
            with self.assertRaises(ValueError): repair.create_version(self.folder, self.base, [edit], 'fixture')

    def test_imports_io_and_initialization_cannot_be_modified(self):
        before = 'import math\nROOT = 1\ndef f():\n    return 1\n'
        for after in (before.replace('import math', 'import os'), before.replace('ROOT = 1', 'ROOT = 2'),
                      before.replace('return 1', "return open('secret').read()")):
            with self.assertRaises(ValueError): repair.validate_edit(before, after, 'design.py')

    def test_registries_can_grow_without_changing_source_paths(self):
        repair.validate_edit("FORMS = {'old': f}\ndef f():\n    return 1\n",
                             "FORMS = {'old': f, 'new': f}\ndef f():\n    return 1\n", 'house.py')

    def test_fresh_worker_uses_patched_code_and_runs_trusted_tests(self):
        version = repair.create_version(self.folder, self.base, [self.edit], 'fixture rhythm repair')
        result = repair.worker(version, 'validate', self.plan, 0, self.folder / 'worker')
        self.assertEqual(result['status'], 'PASS', result.get('log'))
        self.assertGreater(result['tests'], 20)
        actual = load_schematic(self.folder / 'worker/candidate.schem')
        main, _ = design.build(design.plan_for(**self.plan), tier=0)
        from paris_builder.exporter import write_schematic
        write_schematic(self.folder / 'main.schem', main.volume, main.palette)
        self.assertNotEqual(actual.voxel_state_hash(), load_schematic(self.folder / 'main.schem').voxel_state_hash())
        self.assertEqual(read_json(self.folder / 'worker/manifest.json')['generator_version'], version['id'])

    def test_failed_review_repairs_source_then_regenerates_same_intent(self):
        task = w.create_task(self.folder / 'workflow.json', {'style': 'fixture', 'use': 'test', 'scale_budget': {},
            'views': list(w.VIEWS), 'minecraft_version': '1.21.11', 'data_version': 4671}, 'fixture', {'image_input': True})
        task.update(stage='frameworks', intent=self.plan, selected={}, reviews=[]); w.save(task)
        calls = []
        def build(folder, **kwargs):
            calls.append(a.load(folder).get('generator_version'))
            return {'stage': 'frameworks'}
        def review(folder, *args, **kwargs):
            current = a.load(folder)
            if not current.get('generator_version'):
                current['reviews'].append({'stage': 'frameworks', 'decision': 'reject', 'candidates': []})
                w.save(current); raise ValueError('Agent 阶段检查未通过：fixture')
            current['stage'] = 'game'; w.save(current); return {'stage': 'game'}
        version = repair.create_version(self.folder, self.base, [self.edit], 'fixture')
        with patch.object(a, 'build_stage', side_effect=build), patch.object(a, 'agent_review', side_effect=review), \
                patch.object(repair, 'repair_generator', return_value=(version, 'frameworks', {'proposal': {'reason': 'fixture'}})):
            a.run_autonomous(self.folder, 'fixture', 'fixture')
        self.assertEqual(calls, [None, version])
        self.assertEqual(a.load(self.folder)['intent'], self.plan)
        self.assertEqual(a.load(self.folder)['game_acceptance'], 'PENDING')

    def test_model_patch_error_is_returned_as_feedback_then_repaired(self):
        task = {'stage': 'frameworks', 'intent': self.plan, 'brief': {'style': 'fixture'}}
        bad = {'diagnosis': 'generator', 'reason': 'fixture', 'rollback_stage': 'frameworks',
               'edits': [{**self.edit, 'before': 'ambiguous missing source'}]}
        good = {**bad, 'edits': [self.edit]}
        with patch.object(operations, 'DIRECTORY', self.folder / 'operations'), \
                patch('paris_builder.harness_runtime.run_json', side_effect=[(bad, {}), (good, {})]) as model:
            version, rollback, evidence = repair.repair_generator(task, self.folder, {}, 'fixture', 'fixture')
        self.assertEqual(model.call_count, 2)
        self.assertIn('Patch validation:', model.call_args.kwargs['context']['validation_feedback']['log'])
        self.assertEqual(rollback, 'frameworks')
        self.assertEqual(evidence['validation']['status'], 'PASS')
        self.assertEqual(repair.version_files(version)['design.py'].count(self.edit['after']), 1)

    def test_unsupported_diagnosis_with_edits_is_retried(self):
        task = {'stage': 'frameworks', 'intent': self.plan, 'brief': {'style': 'fixture'}}
        good = {'diagnosis': 'supported', 'reason': 'fixture', 'rollback_stage': 'frameworks',
                'edits': [self.edit]}
        contradictory = {**good, 'diagnosis': 'unsupported'}
        with patch.object(operations, 'DIRECTORY', self.folder / 'operations'), \
                patch('paris_builder.harness_runtime.run_json',
                      side_effect=[(contradictory, {}), (good, {})]) as model:
            version, rollback, evidence = repair.repair_generator(
                task, self.folder, {}, 'fixture', 'fixture')
        self.assertEqual(model.call_count, 2)
        self.assertIn('Contradictory repair response',
                      model.call_args.kwargs['context']['validation_feedback']['log'])
        self.assertEqual(rollback, 'frameworks')
        self.assertEqual(evidence['validation']['status'], 'PASS')
        self.assertNotEqual(version['id'], '')

    def test_design_language_preserves_non_paris_rules_and_variation(self):
        language = {'style': 'modern courtyard school', 'invariants': ['clear circulation and daylight'],
                    'variation_axes': ['court layout', 'roof span'], 'relationships': ['classrooms around court'],
                    'uncertainties': []}
        selections = {layer: [{'id': layer, 'layer': layer}] for layer in ('structure', 'facade', 'technique', 'component')}
        inference = {'architectural_contract': language, 'evidence_ids': list(selections),
                     'research_evidence': {'sources': [], 'design_inferences': [], 'boundaries': []}, 'facade_decisions': []}
        with patch.object(operations, 'DIRECTORY', self.folder / 'operations'), patch.object(a, 'measured_advance'):
            task = a.create(self.folder, {**self.plan, 'request': 'courtyard school'}, inference, selections)
        self.assertEqual(task['brief']['design_language'], language)
        self.assertEqual(read_json(self.folder / 'evidence/style_model.json')['style_id'], language['style'])

    def test_capability_gap_triggers_source_extension_before_build(self):
        task = w.create_task(self.folder / 'workflow.json', {'style': 'fixture', 'use': 'test', 'scale_budget': {},
            'views': list(w.VIEWS), 'minecraft_version': '1.21.11', 'data_version': 4671}, 'fixture', {'image_input': True})
        task.update(stage='frameworks', intent=self.plan, selected={}, pending_capability_gaps=['new roof type'])
        w.save(task)
        order = []
        def extend(task, folder, review, *args):
            order.append('extend'); self.assertEqual(review['requested_extensions'], ['new roof type'])
            task['pending_capability_gaps'] = []; w.save(task)
        def build(*args, **kwargs): order.append('build'); raise RuntimeError('stop after extension')
        with patch.object(a, 'apply_generator_repair', side_effect=extend), patch.object(a, 'build_stage', side_effect=build):
            with self.assertRaisesRegex(RuntimeError, 'stop after extension'):
                a.run_autonomous(self.folder, 'fixture', 'fixture')
        self.assertEqual(order, ['extend', 'build'])

    def test_resume_reuses_only_hash_bound_rejection(self):
        task = w.create_task(self.folder / 'workflow.json', {'style': 'fixture', 'use': 'test', 'scale_budget': {},
            'views': list(w.VIEWS), 'minecraft_version': '1.21.11', 'data_version': 4671}, 'fixture', {'image_input': True})
        task.update(stage='frameworks', intent=self.plan, selected={})
        rejection = {'stage': task['stage'], 'revision': task['revision'], 'decision': 'reject',
                     'artifact_hashes': w.bindings(task)}
        for bound in (True, False):
            task['reviews'] = [{**rejection, 'artifact_hashes': rejection['artifact_hashes'] if bound else {'stale': 'hash'}}]
            w.save(task)
            with patch.object(a, 'apply_generator_repair') as extend, \
                    patch.object(a, 'build_stage', side_effect=RuntimeError('checkpoint')):
                with self.assertRaisesRegex(RuntimeError, 'checkpoint'):
                    a.run_autonomous(self.folder, 'fixture', 'fixture')
            self.assertEqual(extend.call_count, int(bound))

    def test_reference_comparisons_preserve_structured_observations(self):
        row = {'comparison': 'Roof section differs', 'observations': {'roof': 'slope break visible'}}
        result = {'references': [row]}
        self.assertTrue(a.normalize_reference_comparisons(result, 1))
        import json
        self.assertEqual(json.loads(result['comparisons'][0]), row)
        self.assertFalse(a.normalize_reference_comparisons({'comparisons': ['only one']}, 5))
        self.assertFalse(a.normalize_reference_comparisons({'comparisons': [{}]}, 1))


if __name__ == '__main__': unittest.main()
