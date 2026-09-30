"""Regression gates for the website production path (fixtures are not acceptance)."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from paris_builder import atelier_workflow as a, design, workflow as w, operations
from paris_builder.architecture import split_state, planar_connection


class AtelierWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.mock = patch.object(operations, 'DIRECTORY', self.root / 'operations')
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def task(self):
        task = w.create_task(self.root / 'workflow.json', {'style': 'test', 'use': 'fixture',
            'scale_budget': {}, 'views': list(w.VIEWS), 'minecraft_version': '1.21.11', 'data_version': 4671},
            'test-fixture', {'image_input': True})
        task.update(stage='frameworks', selected={}, intent={'form': 'street_house',
            'scheme': 'haussmann_apartment', 'width': 12, 'depth': 24, 'storeys': 5, 'seed': 1900})
        w.save(task)
        return task

    def test_framework_stage_yields_one_design(self):
        task = self.task()
        rows = a.plans(task)
        self.assertEqual(len(rows), 1)
        for i, (_, left) in enumerate(rows):
            for _, right in rows[i + 1:]:
                self.assertEqual(sum(left[k] != right[k] for k in ('bay_pitch', 'entrance_fraction', 'roof_height')), 3)
                for k in ('width', 'depth', 'storeys'):
                    self.assertEqual(left[k], task['intent'][k])

    def test_frameworks_do_not_apply_technique_dressing(self):
        scene, report = design.build(design.plan_for('street_house', width=12, depth=24, storeys=5), tier=0)
        self.assertGreater(report['cells'], 0)
        self.assertGreater(sum(wall['openings'] for wall in report['walls']), 0)
        self.assertEqual(report['techniques'], {})

    def contract(self):
        return {'confirmed_brief': 'Confirmed chamfered corner building with mansard roof',
                'architectural_contract': {'style': 'Haussmann', 'invariants': ['chamfer', 'mansard']},
                'unsupported_decisions': ['chamfer geometry'],
                'framework_candidates': [{'parameters': {'bay_pitch': 5, 'roof_height': 7},
                                           'rationale': 'Compliant single design'}]}

    def test_framework_contract_uses_full_history_and_preserves_topology(self):
        task = self.task(); task['intent'].update(session='fixture', form='corner_house')
        history = {'events': [{'kind': 'user', 'text': 'A chamfered corner with mansard'},
                             {'kind': 'assistant', 'text': 'Three street facades'},
                             {'kind': 'user', 'text': 'Confirmed'},
                             {'kind': 'user', 'text': 'Oblique spatial form'}]}
        with patch.object(a, 'read_json', return_value=history), \
             patch('paris_builder.generator_repair.sources', return_value={'design.py': '# fixture'}), \
             patch('paris_builder.harness_runtime.run_json', return_value=(self.contract(), {})) as call:
            a.prepare_framework_contract(task, self.root, 'fixture', 'fixture')
        payload = json.loads(call.call_args.args[2])
        self.assertEqual(len(payload['conversation']), 4)
        self.assertIn('chamfered', payload['conversation'][0]['content'])
        self.assertEqual(call.call_args.kwargs['required_tools'], ('generator_source_map', 'read_generator_source'))
        self.assertEqual(task['brief']['use'], self.contract()['confirmed_brief'])
        self.assertEqual(task['pending_capability_gaps'], ['chamfer geometry'])
        rows = a.plans(task); self.assertEqual(len(rows), 1)
        for _, plan in rows:
            for name in ('form', 'scheme', 'width', 'depth', 'storeys', 'seed'):
                self.assertEqual(plan[name], task['intent'][name])

    def test_framework_contract_rejects_locked_parameter_override(self):
        task = self.task(); task['intent']['session'] = 'fixture'
        proposal = self.contract(); proposal['framework_candidates'][0]['parameters']['form'] = 'street_row'
        with patch.object(a, 'read_json', return_value={'events': []}), \
             patch('paris_builder.generator_repair.sources', return_value={}), \
             patch('paris_builder.harness_runtime.run_json', return_value=(proposal, {})):
            with self.assertRaisesRegex(ValueError, 'form'):
                a.prepare_framework_contract(task, self.root, 'fixture', 'fixture')
        self.assertNotIn('framework_policy', task)

    def test_all_generated_panes_and_bars_have_frozen_connections(self):
        for tier in range(4):
            scene, _ = design.build(design.plan_for('street_house', width=12, depth=24, storeys=5), tier=tier)
            for value in scene.palette:
                name, props = split_state(value)
                if name.endswith('_pane') or name == 'minecraft:iron_bars':
                    self.assertEqual(set(props), {'east', 'west', 'north', 'south', 'waterlogged'})
        _, props = split_state(planar_connection('minecraft:iron_bars', (1, 0)))
        self.assertEqual(props['north'], 'true')
        self.assertEqual(props['east'], 'false')

    def test_cannot_skip_to_refinement_without_review(self):
        task = self.task()
        with self.assertRaisesRegex(ValueError, 'No stage review'):
            w.advance(task)
        self.assertEqual(a.load(self.root)['stage'], 'frameworks')

    def test_autonomous_mode_keeps_the_visual_gate(self):
        task = self.task()
        task['execution_mode'] = 'autonomous'
        with self.assertRaises(ValueError):
            w.submit_review(task, {'stage': 'frameworks', 'revision': task['revision'],
                'artifact_hashes': {}, 'reviewer': 'agent', 'reviewer_type': 'agent',
                'decision': 'pass', 'rationale': 'Cannot advance without actual views', 'candidates': []})
        self.assertEqual(task['stage'], 'frameworks')

    def test_legacy_review_restarts_with_fresh_framework_artifacts(self):
        for stage in ('frameworks', 'tier2', 'delivery'):
            task = self.task(); task.update(stage=stage, review_policy='layered-v1')
            task['selected'] = {'frameworks': {'candidate': 'old'}}
            revision = task['revision']; w.save(task)
            with patch.object(a, 'build_stage', side_effect=RuntimeError('stop before model calls')):
                with self.assertRaisesRegex(RuntimeError, 'stop before model'):
                    a.run_autonomous(self.root, 'fixture', 'fixture')
            revised = a.load(self.root)
            self.assertEqual(revised['stage'], 'frameworks')
            self.assertEqual(revised['revision'], revision + 1)
            self.assertEqual(revised['selected'], {})
            self.assertEqual(revised['review_policy'], 'layered-v2')

    def test_batched_ai_review_keeps_every_view_reference_and_layer(self):
        task = self.task()
        views = {}
        for view in w.VIEWS:
            image = self.root / (view + '.png'); image.write_bytes(b'fixture')
            views[view] = {'path': str(image)}
        references = []
        for index in range(5):
            image = self.root / ('reference-' + str(index) + '.png'); image.write_bytes(b'fixture')
            references.append(str(image))
        template = {'view_observations': dict.fromkeys(w.VIEWS,''),
                    'reference_comparison': dict.fromkeys(references,'')}
        client = MagicMock(); client.config = {}
        def complete(prompt, images=(), max_tokens=0):
            payload = json.loads(prompt)
            if 'views_in_order' in payload:
                result = {'observations': ['actual fixture observation'] * len(images)}
            elif 'review_group' in payload:
                result = {'checks': {key: {'status': 'pass', 'observation': 'fixture section evidence'}
                                     for key in payload['required_output']['checks']}}
            elif 'layer_order' in payload:
                result = {'decision':'pass', 'scores':[18]*5, 'failure_modes':['none'],
                          'layers':[{'status':'pass','observation':'fixture evidence'}]*7,
                          'geometry_checks': {key: {'status': 'pass', 'observation': 'fixture section evidence'}
                                              for key in w.GEOMETRY_CHECKS}}
            else: result = {'comparisons':['fixture comparison']*5}
            return result, {'image_count':len(images)}
        client.complete.side_effect = complete
        data = {'candidates':[{'id':'frame-1','plan':{},'views':views,
                'facade_section': {'status': 'unmeasured', 'reason': 'fixture has no export'}}],
                'references':references,'review_template':{'candidates':[template]}}
        with patch('paris_builder.providers.MultimodalClient', return_value=client), \
                patch.object(a,'summary',return_value=data), patch.object(a,'plans',return_value=[('frame-1',{})]), \
                patch.object(w,'submit_review') as submit, patch.object(w,'advance'):
            a.agent_review(self.root,'fixture-key','fixture-model')
        review = submit.call_args.args[1]
        self.assertEqual(set(review['candidates'][0]['view_observations']),set(w.VIEWS))
        self.assertEqual(len(review['candidates'][0]['reference_comparison']),5)
        self.assertEqual(set(review['candidates'][0]['layer_checks']),set(w.LAYER_CHECKS))
        self.assertEqual(sum(len(call.kwargs['images']) for call in client.complete.call_args_list),28)
        self.assertEqual(review['game_acceptance'],'PENDING')

    def test_detail_batches_cover_every_layer_and_storey_and_preserve_failure(self):
        task = self.task(); task['stage'] = 'facades'
        labels = []
        def checked_call(label, payload, paths, validator):
            labels.append(label)
            if 'review_group' in payload:
                value = {'checks': {key: {'status': 'pass', 'observation': 'visible fixture evidence'}
                                    for key in w.DETAIL_CHECKS}}
                if label == 'checks-storey-2': value['checks']['window_joinery']['status'] = 'fail'
            else:
                self.assertEqual(payload['completed_checks']['storey_checks']['2']['window_joinery']['status'], 'fail')
                value = {'decision': 'reject', 'scores': [10] * 5, 'failure_modes': ['bad window'],
                         'layers': [{'status': 'fail', 'observation': 'fixture defect'}] * 7}
            self.assertTrue(validator(value))
            return value
        result = a.collect_architectural_verdict(task, {'plan': task['intent']}, checked_call)
        self.assertEqual(len(labels), 11)
        self.assertEqual(set(result['detail_checks']), set(w.LAYER_CHECKS[:5]))
        self.assertEqual(set(result['storey_checks']), {str(i) for i in range(5)})
        self.assertEqual(result['decision'], 'reject')
        self.assertTrue(a.architectural_result_valid(task, result))

    def test_detail_batch_rejects_string_checks_with_specific_diagnostic(self):
        task = self.task(); task['stage'] = 'facades'
        def checked_call(label, payload, paths, validator):
            validator({'checks': dict.fromkeys(w.DETAIL_CHECKS, 'pass: unsupported string')})
        with self.assertRaisesRegex(ValueError, 'checks.opening_shape'):
            a.collect_architectural_verdict(task, {'plan': task['intent']}, checked_call)

    def test_framework_cannot_pass_without_roof_form_evidence(self):
        task = self.task()
        candidate = {'decision': 'pass', 'geometry_checks': {
            key: {'status': 'pass', 'observation': 'view evidence'} for key in w.GEOMETRY_CHECKS}}
        w.validate_architectural_checks(task, candidate)
        candidate['geometry_checks']['roof_section']['status'] = 'fail'
        with self.assertRaisesRegex(ValueError, 'roof_section'):
            w.validate_architectural_checks(task, candidate)
        candidate['geometry_checks']['roof_section']['status'] = 'not_applicable'
        with self.assertRaisesRegex(ValueError, 'roof_section'):
            w.validate_architectural_checks(task, candidate)

    def test_detail_gate_rejects_missing_or_failed_window_checks(self):
        task = self.task(); task['stage'] = 'tier2'
        candidate = {'decision': 'pass', 'detail_checks': {layer: {
            key: {'status': 'pass', 'observation': 'each storey inspected'} for key in w.DETAIL_CHECKS}
            for layer in w.LAYER_CHECKS[:5]}, 'storey_checks': {str(i): {
                key: {'status': 'pass', 'observation': 'individual window evidence'} for key in w.DETAIL_CHECKS}
                for i in range(5)}}
        w.validate_architectural_checks(task, candidate)
        candidate['detail_checks']['upper_floors']['surround_sill_lintel']['status'] = 'fail'
        with self.assertRaisesRegex(ValueError, 'surround_sill_lintel'):
            w.validate_architectural_checks(task, candidate)
        candidate['detail_checks']['upper_floors']['surround_sill_lintel']['status'] = 'pass'
        candidate['storey_checks']['2']['window_joinery']['status'] = 'fail'
        with self.assertRaisesRegex(ValueError, 'window_joinery'):
            w.validate_architectural_checks(task, candidate)
        del candidate['detail_checks']['attic']
        with self.assertRaisesRegex(ValueError, 'Every facade'):
            w.validate_architectural_checks(task, candidate)

    def test_autonomous_runner_stops_at_game_without_user_acceptance(self):
        task = self.task()
        task['stage'] = 'delivery'
        w.save(task)
        def deliver(folder, progress=None, emit=None):
            current = a.load(folder); current['stage'] = 'game'; w.save(current)
            return {'stage': 'game', 'run': Path(folder).name}
        with patch.object(a, 'build_stage', side_effect=deliver), patch.object(a, 'agent_review') as reviewer:
            result = a.run_autonomous(self.root, 'fixture-key', 'fixture-model')
        self.assertEqual(result['stage'], 'game')
        self.assertEqual(a.load(self.root)['game_acceptance'], 'PENDING')
        reviewer.assert_not_called()

    def test_nonfinite_scores_are_never_passed(self):
        for bad in (float('nan'), float('inf'), True):
            self.assertIsNotNone(w.score_gate_failure([bad, 20, 20, 20, 20], w.SCORE_PROFILES['strict']))

    def test_artifact_mutation_blocks_progress(self):
        task = self.task()
        evidence = self.root / 'evidence.json'
        evidence.write_text('{}', encoding='utf-8')
        w.register_artifact(task, 'concept', evidence, 'frame-1')
        evidence.write_text('{"changed": true}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Changed or missing'):
            w._check_hashes(task)

    def test_interrupted_operations_recover_and_keep_inputs(self):
        op = operations.Operation('fixture', {'request': 'preserved'}, dependencies=['prior'])
        operations.recover_interrupted()
        saved = json.loads((op.folder / 'operation.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['status'], 'INTERRUPTED')
        self.assertEqual(saved['dependencies'], ['prior'])
        self.assertEqual(saved['inputs'], {'request': 'preserved'})

    def test_failed_operation_is_durable(self):
        op = operations.Operation('fixture', {'attempt': 1})
        op.fail('intentional test failure')
        saved = json.loads((op.folder / 'operation.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['status'], 'FAILED')
        self.assertIn('finished_at', saved)

    def test_delivery_cannot_pass_failed_technical_checks(self):
        task = self.task()
        task['stage'] = 'delivery'
        for kind in w.REQUIRED['delivery']:
            path = self.root / (kind + '.json')
            path.write_text('{"status":"FAIL"}', encoding='utf-8')
            w.register_artifact(task, kind, path)
        with self.assertRaisesRegex(ValueError, 'Delivery technical'):
            w.submit_review(task, {'stage': 'delivery', 'revision': 0, 'artifact_hashes': w.bindings(task),
                'reviewer': 'fixture', 'decision': 'pass', 'rationale': 'test'})

    def test_game_gate_requires_explicit_user_and_all_experiments(self):
        task = self.task()
        task['stage'] = 'game'
        a.record(task, self.root, 'user_acceptance', {'decision': 'accepted', 'user_statement': 'fixture only'})
        a.record(task, self.root, 'state_experiments', {'normal_update_comparison': 'NOT_RUN'})
        review = {'stage': 'game', 'revision': 0, 'artifact_hashes': w.bindings(task),
                  'reviewer': 'fixture', 'reviewer_type': 'model', 'decision': 'pass', 'rationale': 'test'}
        with self.assertRaisesRegex(ValueError, 'Only explicit user'):
            w.submit_review(task, review)
        review['reviewer_type'] = 'user'
        with self.assertRaisesRegex(ValueError, 'experiments incomplete'):
            w.submit_review(task, review)


if __name__ == '__main__':
    unittest.main()
