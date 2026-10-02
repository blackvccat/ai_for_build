"""Export evidence upgrades and interruption must preserve real workflow gates."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from paris_builder import atelier_workflow as a, operations, workflow as w
from paris_builder.cancellation import Cancellation, RunInterrupted, scope
from paris_builder.exporter import write_schematic
from paris_builder.facade_section import REPORT_VERSION, measure


class ReviewEvidencePipelineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        operation_patch = patch.object(operations, 'DIRECTORY', self.root / 'operations')
        operation_patch.start()
        self.addCleanup(operation_patch.stop)
        self.plan = {'form':'corner_house', 'scheme':'haussmann_apartment',
                     'width':8, 'depth':10, 'storeys':2, 'chamfer':3, 'seed':1900}
        self.task = w.create_task(self.root / 'workflow.json', {
            'style':'fixture', 'use':'fixture', 'scale_budget':{}, 'views':list(w.VIEWS),
            'minecraft_version':'1.21.11', 'data_version':4671}, 'fixture', {'image_input':True})
        self.task.update(stage='facades', intent=self.plan,
                         selected={'frameworks':{'candidate':'frame-1','plan':self.plan}},
                         review_policy='layered-v2')
        w.save(self.task)
        self.folder = self.root / 'revision-0' / 'facades' / 'facade-1'
        self.folder.mkdir(parents=True)
        self.schematic = self.folder / 'candidate.schem'
        self.palette = ['minecraft:air', 'minecraft:sandstone', 'minecraft:spruce_planks',
                        'minecraft:glass', 'minecraft:deepslate_tiles']
        self.volume = np.zeros((20,16,14),dtype=np.int32)
        zz,xx = np.mgrid[0:16,0:14]
        footprint = (xx>=2)&(xx<=9)&(zz>=2)&(zz<=11)&(9-xx+zz-2>=3)
        interior = footprint&(xx>2)&(xx<9)&(zz>2)&(zz<11)&(9-xx+zz-2>3)
        self.volume[0,footprint] = 1
        for y in range(1,10):
            self.volume[y,footprint] = 1
            self.volume[y,interior] = 0
        for y in (1,5,9):
            self.volume[y,footprint] = 2
        self.volume[13,footprint] = 4
        self.export()
        w.register_artifact(self.task, 'schematic', self.schematic, 'facade-1')
        a.record(self.task, self.folder, 'assembly_plan', self.plan, 'facade-1')

    def export(self):
        write_schematic(self.schematic,self.volume,self.palette)
        return measure(self.schematic)

    def test_version_upgrade_preserves_old_files_and_review_bindings(self):
        legacy = self.export()
        legacy['version'] = 1
        legacy.pop('roof_slices')
        old_path = a.record(self.task,self.folder,'facade_section',legacy,'facade-1')
        original_file = old_path.read_bytes()
        original_schematic = self.schematic.read_bytes()
        old_bindings = dict(w.bindings(self.task))
        previous = {'stage':'facades','revision':0,'decision':'reject',
                    'artifact_hashes':old_bindings,'rationale':'prior fixture review'}
        self.task['reviews'].append(copy.deepcopy(previous))
        w.save(self.task)

        a.ensure_section_evidence(self.task)

        self.assertEqual(old_path.read_bytes(),original_file)
        self.assertEqual(self.schematic.read_bytes(),original_schematic)
        self.assertEqual(self.task['reviews'],[previous])
        registered = {item['kind']:item for item in w.current_artifacts(self.task)}
        upgraded = registered['facade_section']
        self.assertEqual(Path(upgraded['path']).name,f'facade_section-v{REPORT_VERSION}.json')
        self.assertNotEqual(Path(upgraded['path']),old_path)
        report = json.loads(Path(upgraded['path']).read_text(encoding='utf-8'))
        self.assertEqual(report['version'],REPORT_VERSION)
        self.assertEqual(report['source']['sha256'],w.sha(self.schematic))
        self.assertIn('roof_slices',report)
        description = registered['architectural_evidence']
        payload = json.loads(Path(description['path']).read_text(encoding='utf-8'))
        self.assertEqual(payload['source'],report['source'])
        self.assertNotIn(str(old_path.resolve()),w.bindings(self.task))
        self.assertIn(str(old_path.resolve()),previous['artifact_hashes'])
        self.assertNotEqual(w.bindings(self.task),old_bindings)
        self.assertEqual(a.load(self.root)['reviews'],[previous])
        bindings = dict(w.bindings(self.task))
        a.ensure_section_evidence(self.task)
        self.assertEqual(w.bindings(self.task),bindings)
        w._check_hashes(self.task)

    def test_supported_dimension_mismatch_blocks_reusable_candidate(self):
        wrong_plan = {**self.plan,'width':9}
        a.record(self.task,self.folder,'assembly_plan',wrong_plan,'facade-1')
        with self.assertRaisesRegex(ValueError,'Measured export differs from plan.*width'):
            a.ensure_section_evidence(self.task,validate_plan=True)
        self.assertEqual(a.load(self.root)['stage'],'facades')
        self.assertEqual(a.load(self.root)['game_acceptance'],'PENDING')

    def test_direct_review_blocks_measured_mismatch_before_constructing_model_client(self):
        a.record(self.task,self.folder,'assembly_plan',{**self.plan,'width':9},'facade-1')
        with patch('paris_builder.providers.MultimodalClient') as client:
            with self.assertRaisesRegex(ValueError,'Measured export differs from plan.*width'):
                a.agent_review(self.root,'fixture-key','fixture-model')
        client.assert_not_called()
        self.assertEqual(a.load(self.root)['reviews'],[])

    def test_actual_party_glazing_mutation_cannot_be_overruled_by_a_pass(self):
        clean = self.export()
        a.check_measured_plan(self.plan,clean)
        self.volume[2,7,2] = 3
        changed = self.export()
        west = changed['storeys'][0]['faces']['party_west']
        self.assertEqual(west['sampled_transmissive_groups_count'],1)
        self.assertEqual(west['openings'][0]['sample_coordinates_xyz'],[[2,2,7]])
        self.assertNotEqual(changed['source']['sha256'],clean['source']['sha256'])
        with self.assertRaisesRegex(ValueError,'party_west.sampled_transmissive_groups'):
            a.check_measured_plan(self.plan,changed)

    def test_unsupported_sampler_remains_unresolved_without_an_overall_pass(self):
        report = self.export()
        unsupported = {**self.plan,'form':'street_house','width':999}
        a.check_measured_plan(unsupported,report)
        payload = a.model_section_evidence(report,unsupported)
        self.assertTrue(all(check['status']=='unsupported' for check in payload['plan_comparison']['checks']))
        self.assertNotIn('decision',payload)
        self.assertNotIn('overall_pass',payload['plan_comparison'])
        self.assertEqual(self.task['game_acceptance'],'PENDING')

    def test_optional_text_retains_same_plan_comparison_and_export_hashes(self):
        report = self.export()
        frozen = json.dumps(report)
        arrays = a.model_section_evidence(report,self.plan,storey=0)
        text = a.model_section_evidence(report,self.plan,storey=0,presentation='text')
        self.assertIn('surface_maps',arrays)
        self.assertIn('palette',arrays)
        self.assertIn('roof_slices',arrays)
        self.assertNotIn('readable_diagrams',arrays)
        self.assertNotIn('surface_maps',text)
        self.assertNotIn('palette',text)
        self.assertNotIn('roof_slices',text)
        self.assertIn('FACE party_west',text['readable_diagrams'])
        self.assertIn('ROOF VOXEL SLICES',text['readable_diagrams'])
        self.assertEqual(text['source'],report['source'])
        self.assertEqual(arrays['source'],text['source'])
        self.assertEqual(arrays['plan_comparison'],text['plan_comparison'])
        self.assertIn(report['source']['sha256'],text['readable_diagrams'])
        self.assertIn(report['source']['voxel_state_hash'],text['readable_diagrams'])
        self.assertEqual(json.dumps(report),frozen)

    def test_storey_review_batches_receive_selected_text_and_plan_diff(self):
        report = self.export()
        self.task['evidence_presentation'] = 'text'
        captured = {}
        def checked(label,payload,paths,validator):
            captured[label] = payload
            if 'review_group' in payload:
                value = {'checks':{key:{'status':'pass','observation':'fixture evidence'}
                                   for key in payload['required_output']['checks']}}
            else:
                value = {'decision':'pass','scores':[18]*5,'failure_modes':['fixture only'],
                         'layers':[{'status':'pass','observation':'fixture evidence'}]*len(w.LAYER_CHECKS)}
            self.assertTrue(validator(value))
            return value
        a.collect_architectural_verdict(self.task,{'plan':self.plan,'facade_section':report},checked)
        for i in range(2):
            payload = captured[f'checks-storey-{i}']['facade_section']
            self.assertEqual(payload['source'],report['source'])
            self.assertEqual(payload['plan_comparison']['source'],report['source'])
            self.assertIn(f'facade scope: storey={i}',payload['readable_diagrams'])
            self.assertNotIn('surface_maps',payload)
        self.assertEqual(self.task['reviews'],[])
        self.assertEqual(self.task['stage'],'facades')

    def test_cancel_during_actual_review_does_not_retry_sleep_or_repair(self):
        report = self.export()
        image = self.root / 'front.png'
        image.write_bytes(b'fixture image, not a visual acceptance')
        references = []
        for i in range(5):
            path = self.root / f'reference-{i}.png'
            path.write_bytes(b'fixture reference')
            references.append(str(path))
        data = {'candidates':[{'id':'facade-1','plan':self.plan,
                'views':{'front':{'path':str(image)}},'facade_section':report}],
                'references':references,'review_template':{'candidates':[{
                    'view_observations':{'front':''},'reference_comparison':dict.fromkeys(references,'')} ]}}
        token = Cancellation()
        client = MagicMock()
        client.config = {}
        def complete(prompt,images=(),max_tokens=0):
            token.request()
            return {'observations':['fixture pixel observation']},{'image_count':len(images)}
        client.complete.side_effect = complete
        with patch.object(a,'prepare_framework_contract'), \
             patch.object(a,'build_stage',return_value={'stage':'facades'}), \
             patch.object(a,'summary',return_value=data), \
             patch('paris_builder.providers.MultimodalClient',return_value=client), \
             patch.object(a,'apply_generator_repair') as repair, \
             patch.object(a.time,'sleep') as sleep, \
             patch.object(w,'submit_review') as submit, scope(token):
            with self.assertRaises(RunInterrupted):
                a.run_autonomous(self.root,'fixture-key','fixture-model')
        self.assertEqual(client.complete.call_count,1)
        sleep.assert_not_called()
        repair.assert_not_called()
        submit.assert_not_called()
        stopped = a.load(self.root)
        self.assertEqual(stopped['stage'],'facades')
        self.assertEqual(stopped['awaiting'],'AGENT_INTERRUPTED_facades')
        self.assertEqual(stopped['reviews'],[])
        self.assertFalse(any('agent_review_error' in row for row in stopped['history']))
        self.assertFalse(any('generator_repair' in row for row in stopped['history']))
        self.assertEqual(stopped['game_acceptance'],'PENDING')


if __name__ == '__main__':
    unittest.main()
