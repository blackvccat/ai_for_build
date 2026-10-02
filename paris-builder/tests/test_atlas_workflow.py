"""Controlled atlas integration: real evidence gates, no provider or game claims.

Small scenes exercise workflow persistence and source-piece audits. Rendering and
the whole-house assembler are mocked where the test concerns directory plumbing;
hash validation, review advancement, schematic readback and stamp audits are real.
"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
from PIL import Image

from paris_builder import atelier_workflow as a, atlas_assembly, design, operations
from paris_builder import workflow as w
from paris_builder.architecture import Scene
from paris_builder.exporter import write_schematic
from paris_builder.schematic import load_schematic


class AtlasWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=operations.ROOT / 'runs')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.operations = patch.object(operations, 'DIRECTORY', self.root / 'operations')
        self.operations.start()
        self.addCleanup(self.operations.stop)

    def task(self, stage='frameworks'):
        task = w.create_task(self.root / 'workflow.json', {
            'style': 'offline atlas fixture', 'use': 'test workflow, not acceptance',
            'scale_budget': {'width': 46, 'depth': 42}, 'views': list(w.VIEWS),
            'minecraft_version': '1.21.11', 'data_version': 4671,
        }, 'offline fixture', {'image_input': True})
        task.update(stage=stage, selected={}, review_policy='layered-v2', intent={
            'form': 'corner_house', 'scheme': 'haussmann_apartment',
            'width': 46, 'depth': 42, 'storeys': 6, 'seed': 1901,
            'detail_profile': 'atlas_street1', 'composition_profile': 'grouped_pavilions',
        })
        w.save(task)
        return task

    def bare_scene(self):
        scene = Scene(5, 5, 5)
        for y in range(3):
            scene.put(2, y, 2, 'minecraft:smooth_sandstone')
        return scene

    def bare_manifest(self):
        return {'techniques': [], 'stamps': [], 'stamp_audit': [],
                'stamp_audit_rows': [], 'stamp_audit_policy': [],
                'source_trace': {'status': 'NOT_APPLICABLE'},
                'atlas_audit': {'status': 'NOT_APPLICABLE'},
                'atlas_tier_semantics': 'bare_massing',
                'composition': {'mode': 'grouped_pavilions'},
                'atlas_frame_spec': {'fixture': 'not an accepted architecture'}}

    def images(self):
        path = self.root / 'offline-view.png'
        Image.new('RGB', (8, 8), (120, 120, 120)).save(path)
        return {view: path for view in a.fixed_view_bundle.__globals__['FIXED_VIEWS']}

    def offline_review(self, task):
        data = a.summary(self.root)
        rows = []
        for candidate in data['candidates']:
            observation = 'Offline plumbing fixture only; no architectural approval'
            group = lambda keys: {key: {'status': 'pass', 'observation': observation} for key in keys}
            rows.append({'id': candidate['id'], 'decision': 'pass', 'scores': [18] * 5,
                         'view_observations': {key: observation for key in candidate['views']},
                         'reference_comparison': {str(i): observation for i in range(5)},
                         'failure_modes': [observation], 'geometry_checks': group(w.GEOMETRY_CHECKS),
                         'layer_checks': group(w.LAYER_CHECKS),
                         'detail_checks': {key: group(w.DETAIL_CHECKS) for key in w.LAYER_CHECKS[:5]},
                         'storey_checks': {str(i): group(w.DETAIL_CHECKS) for i in range(6)}})
        review = {'stage': task['stage'], 'revision': task['revision'], 'artifact_hashes': w.bindings(task),
                  'reviewer': 'offline fixture', 'reviewer_type': 'agent',
                  'decision': 'pass', 'selected': rows[0]['id'],
                  'rationale': 'Offline persistence/gate fixture, no acceptance', 'candidates': rows}
        with patch.object(a, 'retain_candidate_review'):
            a.submit_review(self.root, review)
        return a.load(self.root)

    def passed_framework(self):
        """Real layered workflow gate with explicit offline visual observations."""
        task = self.task()
        ident, spec = a.plans(task)[0]
        scene = self.bare_scene()
        schematic = self.root / 'framework.schem'
        write_schematic(schematic, scene.volume, scene.palette)
        w.register_artifact(task, 'schematic', schematic, ident)
        a.record(task, self.root, 'concept', spec, ident)
        a.record(task, self.root, 'technical_validation',
                 load_schematic(schematic).validation(), ident)
        views = a.fixed_view_bundle(self.images())
        a.record(task, self.root, 'views', views, ident, view_set='reduced')
        row = {'id': ident, 'decision': 'pass', 'scores': [18] * 5,
               'view_observations': {key: 'Offline fixture observation' for key in views},
               'reference_comparison': {str(i): 'Offline fixture comparison' for i in range(5)},
               'failure_modes': ['No fixture failure; not architectural acceptance'],
               'geometry_checks': {key: {'status': 'pass', 'observation': 'Offline fixture: ' + key}
                                   for key in w.GEOMETRY_CHECKS},
               'layer_checks': {key: {'status': 'not_applicable', 'observation': 'Bare offline fixture'}
                                for key in w.LAYER_CHECKS}}
        review = {'stage': 'frameworks', 'revision': 0, 'artifact_hashes': w.bindings(task),
                  'reviewer': 'offline fixture', 'reviewer_type': 'agent',
                  'decision': 'pass', 'selected': ident,
                  'rationale': 'Offline persistence/gate fixture, no acceptance', 'candidates': [row]}
        w.submit_review(task, review)
        task['selected']['frameworks'] = {'candidate': ident, 'plan': spec}
        w.advance(task)
        return task

    def test_intent_profile_and_composition_survive_stage_plans(self):
        task = self.task()
        frame = a.plans(task)[0][1]
        self.assertEqual(frame['detail_profile'], 'atlas_street1')
        self.assertEqual(frame['composition_profile'], 'grouped_pavilions')
        self.assertNotIn('storeys', frame)  # The kit owns its source layer sequence.
        design.plan_for(**frame)  # Real plan validation must accept the result.
        task['selected']['frameworks'] = {'candidate': 'frame-1', 'plan': frame}
        task['stage'] = 'facades'
        facade = a.plans(task)[0][1]
        self.assertEqual(facade['composition_profile'], frame['composition_profile'])
        task['selected']['facades'] = {'candidate': 'facade-1', 'plan': facade}
        task['stage'] = 'tier2'
        self.assertEqual(a.plans(task)[0][1], facade)

    def test_non_atlas_plan_keeps_explicit_storeys(self):
        task = self.task()
        task['intent'].pop('detail_profile')
        task['intent'].pop('composition_profile')
        self.assertEqual(a.plans(task)[0][1]['storeys'], 6)

    def test_empty_kit_framework_parameters_are_valid_but_pitch_is_not(self):
        proposal = {'confirmed_brief': 'Preserve source layers and the player plot budget',
                    'architectural_contract': {'style': 'test', 'invariants': ['two street wings']},
                    'unsupported_decisions': [],
                    'framework_candidate': {'parameters': {}, 'rationale': 'Keep confirmed kit shape'}}
        task = self.task()
        task['intent']['session'] = 'fixture'
        with patch.object(a, 'read_json', return_value={'events': []}), \
             patch('paris_builder.generator_repair.sources', return_value={}), \
             patch('paris_builder.harness_runtime.run_json', return_value=(proposal, {})) as provider:
            a.prepare_framework_contract(task, self.root, 'offline', 'offline')
        payload = json.loads(provider.call_args.args[2])
        self.assertIn('source kit owns storeys', payload['instruction'])
        self.assertEqual(a.plans(task)[0][1]['composition_profile'], 'grouped_pavilions')
        proposal['framework_candidate']['parameters'] = {'bay_pitch': 6}
        task = self.task()
        task['intent']['session'] = 'fixture'
        with patch.object(a, 'read_json', return_value={'events': []}), \
             patch('paris_builder.generator_repair.sources', return_value={}), \
             patch('paris_builder.harness_runtime.run_json', return_value=(proposal, {})):
            with self.assertRaisesRegex(ValueError, '件库固定'):
                a.prepare_framework_contract(task, self.root, 'offline', 'offline')

    def test_cannot_advance_or_build_details_without_framework_review(self):
        task = self.task()
        with self.assertRaisesRegex(ValueError, 'No stage review'):
            w.advance(task)
        task['stage'] = 'tier2'
        w.save(task)
        with patch.object(a, 'candidate') as build:
            with self.assertRaisesRegex(ValueError, 'passed selected frameworks'):
                a.build_stage(self.root)
            build.assert_not_called()
        self.assertEqual(w.load(task['path'])['game_acceptance'], 'PENDING')

    def test_selected_flags_cannot_replace_actual_review_evidence(self):
        task = self.task('facades')
        task['selected']['frameworks'] = {'candidate': 'frame-1', 'plan': a.plans(self.task())[0][1]}
        task['reviews'] = [{'stage': 'frameworks', 'revision': 0, 'decision': 'pass',
                            'selected': 'frame-1', 'artifact_hashes': {},
                            'reviewer': 'forged', 'rationale': 'unsupported pass claim'}]
        with self.assertRaisesRegex(ValueError, 'Expected 1 candidates|Missing required'):
            a.require_atlas_prior_reviews(task)

    def test_review_revalidation_preserves_valid_earlier_revision_after_rollback(self):
        task = self.passed_framework()
        w.rollback(task, 'facades', 'Offline refinement repair retains approved massing')
        self.assertEqual(task['revision'], 1)
        a.require_atlas_prior_reviews(task)
        image = self.root / 'offline-view.png'
        image.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'reviewed image changed'):
            a.require_atlas_prior_reviews(task)

    def test_selected_plan_cannot_change_after_framework_approval(self):
        task = self.passed_framework()
        task['selected']['frameworks']['plan']['composition_profile'] = 'flat_baseline'
        with self.assertRaisesRegex(ValueError, 'selected plan differs'):
            a.require_atlas_prior_reviews(task)

    def test_candidate_uses_distinct_project_workdirs_and_carries_frame_targets(self):
        task = self.task()
        ident, spec = a.plans(task)[0]
        manifest, scene = self.bare_manifest(), self.bare_scene()
        out = self.root / 'frameworks' / ident
        with patch.object(design, 'build', return_value=(scene, manifest)) as build, \
             patch.object(a, 'render_previews', return_value=self.images()), \
             patch.object(a.subprocess, 'run') as registry:
            registry.return_value.returncode = 0
            a.candidate(task, out, ident, spec, size=64)
        self.assertEqual([call.kwargs['work_dir'] for call in build.call_args_list],
                         [out / 'atlas-work', out / 'atlas-work-repeat'])
        concept = json.loads((out / 'concept.json').read_text(encoding='utf-8'))
        self.assertEqual(concept['composition'], manifest['composition'])
        self.assertEqual(concept['atlas_frame_spec'], manifest['atlas_frame_spec'])
        technical = json.loads((out / 'technical_validation.json').read_text(encoding='utf-8'))
        self.assertEqual(technical['stamp_audit']['status'], 'NOT_APPLICABLE')
        self.assertEqual(technical['status'], 'PASS')
        generation = next(item for item in task['artifacts'] if item['kind'] == 'generation_manifest')
        self.assertEqual(w.sha(generation['path']), generation['sha256'])
        self.assertEqual(task['stage'], 'frameworks')  # A build never grants visual approval.

    def test_full_kit_in_framework_is_a_persisted_technical_failure(self):
        task = self.task()
        ident, spec = a.plans(task)[0]
        manifest = self.bare_manifest()
        manifest['atlas_tier_semantics'] = 'post_framework_complete_kit'
        out = self.root / 'invalid-framework'
        with patch.object(design, 'build', return_value=(self.bare_scene(), manifest)), \
             patch.object(a.subprocess, 'run') as registry, \
             patch.object(a, 'render_previews') as render:
            registry.return_value.returncode = 0
            with self.assertRaisesRegex(ValueError, 'technical validation failed'):
                a.candidate(task, out, ident, spec, size=64)
            render.assert_not_called()
        technical = json.loads((out / 'technical_validation.json').read_text(encoding='utf-8'))
        self.assertEqual(technical['status'], 'FAIL')
        self.assertIn('bare massing', technical['atlas_failures'][0])

    def source_piece(self):
        """One real derived window, with source replay and real exported-state audit."""
        original = atlas_assembly.load_piece('v4:st1-window-bay-standard')
        height, depth, width = original.volume.shape
        asm = atlas_assembly.Assembler(Scene(width, height, depth), self.root / 'derived')
        ident = 'derived:workflow-window@identity'
        # Node registry execution is covered separately; all provenance checks
        # and state replay here remain real. No source/library files are changed.
        with patch.object(atlas_assembly, 'validate_vanilla', return_value={'status': 'PASS'}):
            asm.register_derived(ident, original.volume, original.id_to_state,
                                 'Offline identity-derived audit fixture',
                                 source_id='v4:st1-window-bay-standard', operations=[])
            asm.stamp(ident, 0, 0, 0, 'window-fixture')
        path = self.root / 'source-window.schem'
        write_schematic(path, asm.scene.volume, asm.scene.palette)
        read = load_schematic(path)
        manifest = {'atlas_tier_semantics': 'post_framework_complete_kit',
                    'stamp_audit': asm.audit_entries(), 'stamp_audit_rows': asm.audit_rows(),
                    'stamp_audit_policy': [], 'source_trace': {'status': 'PASS'},
                    'atlas_audit': {'status': 'PASS'}, 'stamps': asm.stamps,
                    'composition': {'mode': 'grouped_pavilions'}, 'techniques': []}
        return read, manifest

    def test_offline_stage_chain_packages_source_audit_and_keeps_user_game_gate(self):
        """Small real export/audit fixtures; no provider or architecture acceptance."""
        task = self.task()
        read, manifest = self.source_piece()
        height, depth, width = read.volume.shape
        detailed = Scene(width, height, depth)
        detailed.palette = list(read.id_to_state)
        detailed.volume = read.volume.copy()

        def build(plan, tier=3, work_dir=None):
            return (self.bare_scene(), self.bare_manifest()) if tier < 2 else (detailed, manifest)

        images = self.images()
        images.update({f'orbit_{height}_{angle:03d}': self.root / 'offline-view.png'
                       for height in ('street', 'high') for angle in range(0, 360, 45)})
        with patch.object(design, 'build', side_effect=build), \
             patch.object(a, 'inspect_geometry', return_value={'status': 'PASS'}), \
             patch.object(a, 'render_previews', return_value=images), \
             patch.object(a.subprocess, 'run') as registry:
            registry.return_value.returncode = 0
            for stage in ('frameworks', 'facades', 'tier2', 'tier3'):
                self.assertEqual(a.load(self.root)['stage'], stage)
                if stage == 'tier2':
                    manifest['composition']['mode'] = 'changed_after_framework_review'
                    with self.assertRaisesRegex(ValueError, 'technical validation failed'):
                        a.build_stage(self.root, size=64)
                    failed = next(item for item in w.current_artifacts(a.load(self.root))
                                  if item['kind'] == 'technical_validation')
                    receipt = json.loads(Path(failed['path']).read_text(encoding='utf-8'))
                    self.assertIn('rollback to frameworks', receipt['atlas_failures'][-1])
                    manifest['composition']['mode'] = 'grouped_pavilions'
                result = a.build_stage(self.root, size=64)
                self.assertEqual(result['status'], 'AWAITING_VISUAL_REVIEW')
                task = self.offline_review(a.load(self.root))
                if stage == 'facades':
                    # A forged stage pointer cannot skip the real tier2 gate.
                    skipped = {**task, 'stage': 'tier3'}
                    with self.assertRaisesRegex(ValueError, 'passed selected tier2'):
                        a.require_atlas_prior_reviews(skipped)
            self.assertEqual(task['stage'], 'delivery')
            result = a.build_stage(self.root)
        self.assertEqual(result['stage'], 'game')
        self.assertEqual(a.load(self.root)['game_acceptance'], 'PENDING')
        with zipfile.ZipFile(self.root / 'delivery.zip') as archive:
            self.assertTrue({'assembly.json', 'generation_manifest.json', 'source_piece_audit.json',
                             'candidate.schem', 'STATE-LAB.schem'} <= set(archive.namelist()))
            final_audit = json.loads(archive.read('source_piece_audit.json'))
            self.assertEqual(final_audit['status'], 'PASS')
            self.assertGreater(final_audit['matched_cells'], 0)
            snapshot = json.loads(archive.read('workflow_snapshot.json'))
            self.assertEqual(snapshot['game_acceptance'], 'PENDING')
            self.assertEqual(snapshot['stage'], 'game')

    def test_atlas_visual_scope_requires_relief_at_framework_and_full_kit_at_tier2(self):
        task = self.task()
        scope = a.atlas_visual_scope(task)
        self.assertIn('projecting base and plinth', scope)
        self.assertIn('stepped projecting cornice', scope)
        self.assertIn('Missing or visually unreadable massing elements are defects', scope)
        self.assertIn('north and west', scope)
        task['stage'] = 'tier2'
        scope = a.atlas_visual_scope(task)
        self.assertIn('complete source kit', scope)
        self.assertIn('Concrete structural regressions require rollback', scope)

    def test_derived_rows_are_used_and_missing_rows_cannot_fall_back_to_catalogue(self):
        read, manifest = self.source_piece()
        audit, failures = a.audit_atlas_generation(read, manifest, 'tier2')
        self.assertEqual(failures, [])
        self.assertEqual(audit['status'], 'PASS')
        self.assertGreater(audit['matched_cells'], 0)
        manifest.pop('stamp_audit_rows')
        audit, failures = a.audit_atlas_generation(read, manifest, 'tier2')
        self.assertEqual(audit['status'], 'FAIL')
        self.assertTrue(any('actual original and derived' in error for error in failures))

    def test_mutated_export_and_failed_source_receipt_block_details(self):
        read, manifest = self.source_piece()
        manifest['source_trace']['status'] = 'FAIL'
        _, failures = a.audit_atlas_generation(read, manifest, 'tier3')
        self.assertIn('Atlas source_trace did not pass', failures)
        manifest['source_trace']['status'] = 'PASS'
        coordinate = tuple(np.argwhere(read.volume != 0)[0])
        read.volume[coordinate] = 0
        audit, failures = a.audit_atlas_generation(read, manifest, 'tier3')
        self.assertEqual(audit['status'], 'FAIL')
        self.assertIn('Exported atlas source-piece placement audit failed', failures)


if __name__ == '__main__':
    unittest.main()
