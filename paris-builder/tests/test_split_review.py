"""Split review acceptance uses real export predicates and six quality answers.

Images and quality observations below are labelled offline fixtures. These tests
verify the control loop; they are neither architectural perception nor acceptance.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from paris_builder import architectural_conformance as c, atelier_workflow as a, workflow as w
from paris_builder.exporter import write_schematic


class SplitReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.palette = ['minecraft:air','minecraft:sandstone','minecraft:spruce_planks',
                        'minecraft:glass','minecraft:deepslate_tiles']
        self.profile = [0,2,4,6,7,7,8,8,8,9,9,9,10]
        self.plan = {'form':'corner_house','scheme':'haussmann_apartment','width':25,'depth':31,
                     'storeys':2,'chamfer':3,'seed':1900}
        self.task = w.create_task(self.root/'workflow.json',
            {'style':'offline fixture','use':'control-loop test','scale_budget':{},'views':list(w.VIEWS),
             'minecraft_version':'1.21.11','data_version':4671},'offline-fixture',{'image_input':True})
        self.task.update(stage='facades',review_policy=w.SPLIT_REVIEW_POLICY,
                         intent=deepcopy(self.plan),selected={'frameworks':{'candidate':'frame-1','plan':deepcopy(self.plan)}})
        self.ident = 'facade-1'
        self.make_export()
        image = self.root/'offline-placeholder.png'
        Image.new('RGB',(16,16),(100,120,140)).save(image)
        self.views = {name:{'path':str(image),'sha256':w.sha(image)} for name in w.VIEWS}
        self.record('assembly_plan',self.plan)
        self.record('technical_validation',{'status':'PASS','evidence':'offline fixture export'})
        self.record('views',self.views)
        self.refresh_conformance()

    def make_export(self, profile=None):
        profile = profile or self.profile
        v = np.zeros((34,35,29),dtype=np.int32)
        for z in range(2,33):
            for x in range(2,27):
                if 26-x+z-2 >= 3:
                    v[0,z,x] = 1
        for y in (1,5,9):
            v[y] = np.where(v[0],2,0)
        v[1:10,2:4,2:24] = 1
        v[1:10,5:33,25:27] = 1
        v[1:10,2:33,2] = 1
        v[1:10,32,2:27] = 1
        for x,z in ((23,2),(24,3),(25,4),(26,5)):
            v[1:10,z,x] = 1
        for low in (2,6):
            v[low:low+3,2,6:8] = 0
            v[low:low+3,3,6:8] = 3
            v[low:low+3,10:12,26] = 0
            v[low:low+3,10:12,25] = 3
            v[low:low+3,3,24] = 0
            v[low:low+3,4,23] = 3
        for z in range(2,33):
            for x in range(2,27):
                if v[0,z,x]:
                    high = 10+profile[min(x-2,26-x,z-2,32-z)]
                    v[max(10,high-1):high+1,z,x] = 4
        self.schematic = self.root/'candidate.schem'
        write_schematic(self.schematic,v,self.palette)
        w.register_artifact(self.task,'schematic',self.schematic,self.ident)

    def record(self,kind,value):
        path = self.root/(kind+'.json')
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        w.register_artifact(self.task,kind,path,self.ident)
        return path

    def refresh_conformance(self):
        self.conformance = c.measure(self.schematic,self.plan,stage=self.task['stage'])
        self.conformance_path = self.record('architectural_conformance',self.conformance)

    def review(self,scores=None):
        row = {'id':self.ident,'decision':'pass','scores':[18]*5 if scores is None else scores,
               'quality_checks':{key:{'status':'pass','observation':'offline quality fixture: '+key} for key in w.QUALITY_CHECKS},
               'view_observations':{key:'offline view fixture' for key in self.views},
               'reference_comparison':{str(index):'offline reference comparison' for index in range(5)},
               'failure_modes':['none, offline fixture']}
        return {'stage':self.task['stage'],'revision':self.task['revision'],'artifact_hashes':w.bindings(self.task),
                'reviewer':'offline fixture','reviewer_type':'agent','decision':'pass','selected':self.ident,
                'rationale':'Control loop fixture with six explicitly passing quality answers.','candidates':[row]}

    def test_split_pass_uses_six_questions_without_legacy_ninety_five_checks(self):
        self.assertEqual(self.conformance['status'],'PASS')
        review = self.review()
        self.assertEqual(len(review['candidates'][0]['quality_checks']),6)
        self.assertFalse(set(review['candidates'][0]) & {'layer_checks','geometry_checks','detail_checks','storey_checks'})
        w.submit_review(self.task,review)
        w.advance(self.task)
        self.assertEqual(self.task['stage'],'tier2')
        self.assertEqual(self.task['game_acceptance'],'PENDING')

    def test_split_summary_exposes_quality_template_and_conformance(self):
        data = a.summary(self.root)
        template = data['review_template']['candidates'][0]
        self.assertEqual(set(template['quality_checks']),set(w.QUALITY_CHECKS))
        self.assertFalse(set(template) & {'layer_checks','geometry_checks','detail_checks','storey_checks'})
        self.assertEqual(data['candidates'][0]['conformance']['status'],'PASS')

    def test_missing_geometry_receipt_blocks_even_perfect_quality(self):
        self.task['artifacts'] = [artifact for artifact in self.task['artifacts'] if artifact['kind']!='architectural_conformance']
        with self.assertRaisesRegex(ValueError,'requires measured conformance'):
            w.submit_review(self.task,self.review([20]*5))

    def test_final_reference_source_details_cannot_be_replaced_by_visual_pass(self):
        self.task['stage'] = 'tier3'
        self.task['source_state_policy'] = 'source-special-v1'
        for artifact in self.task['artifacts']:
            artifact['stage'] = 'tier3'
        self.refresh_conformance()
        with self.assertRaisesRegex(ValueError,'require source-state evidence'):
            w.submit_review(self.task,self.review([20]*5))
        self.assertEqual(self.task['stage'],'tier3')
        self.assertEqual(self.task['game_acceptance'],'PENDING')

    def test_final_reference_profile_enforces_source_gate_without_optional_flag(self):
        self.task['intent']['detail_profile'] = 'reference_haussmann'
        self.task['stage'] = 'tier3'
        self.assertTrue(w.source_states_required(self.task))
        self.task['stage'] = 'tier2'
        self.assertFalse(w.source_states_required(self.task))

    def test_quality_cannot_override_bad_roof_geometry(self):
        self.make_export(list(range(13)))
        self.refresh_conformance()
        self.assertEqual(self.conformance['status'],'FAIL')
        self.assertEqual(next(x for x in self.conformance['checks'] if x['id']=='corner/chamfer_geometry')['status'],'pass')
        with self.assertRaisesRegex(ValueError,'Measured conformance is unresolved'):
            w.submit_review(self.task,self.review([20]*5))

    def test_forged_geometry_pass_with_reregistered_hash_is_recomputed(self):
        self.make_export(list(range(13)))
        self.refresh_conformance()
        report = deepcopy(self.conformance)
        for check in report['checks']:
            check['status'] = 'pass'
        report['summary'] = {'pass':len(report['checks']),'fail':0,'unsupported':0,'required_fail':0,'required_unsupported':0}
        report['status'] = 'PASS'
        self.record('architectural_conformance',report)
        with self.assertRaisesRegex(ValueError,'independently recomputed'):
            w.submit_review(self.task,self.review([20]*5))

    def test_geometry_rejection_records_without_inventing_model_perception(self):
        self.make_export(list(range(13)))
        self.refresh_conformance()
        review = {'stage':self.task['stage'],'revision':self.task['revision'],'artifact_hashes':w.bindings(self.task),
                  'reviewer':'export-conformance-validator','reviewer_type':'software','scope':'deterministic_conformance',
                  'decision':'reject','selected':None,'rollback_stage':self.task['stage'],
                  'rationale':'Measured roof has no qualifying slope break.',
                  'candidates':[{'id':self.ident,'decision':'reject','conformance_status':'FAIL',
                                 'failure_modes':['Measured roof slope defect.']}]}
        w.submit_review(self.task,review)
        row = self.task['reviews'][-1]['candidates'][0]
        self.assertNotIn('quality_checks',row)
        self.assertNotIn('view_observations',row)
        self.assertNotIn('scores',row)
        with self.assertRaisesRegex(ValueError,'Rejected stage'):
            w.advance(self.task)

    def test_agent_skips_paid_quality_calls_for_failed_geometry_and_records_reject(self):
        self.make_export(list(range(13)))
        self.refresh_conformance()
        with patch('paris_builder.providers.MultimodalClient') as client:
            with self.assertRaisesRegex(ValueError,'Agent 阶段检查未通过'):
                a.agent_review(self.root,'offline-fixture-key','offline-fixture-model')
            client.assert_not_called()
        task = w.load(self.root/'workflow.json')
        review = task['reviews'][-1]
        self.assertEqual(review['decision'],'reject')
        self.assertEqual(review['reviewer_type'],'software')
        self.assertEqual(task['stage'],'facades')
        self.assertNotIn('view_observations',review['candidates'][0])
        self.assertTrue(a.summary(self.root)['candidate_search']['candidates_retained'])

    def test_low_and_high_framework_scores_are_descriptive(self):
        self.task['stage'] = 'frameworks'
        for artifact in self.task['artifacts']:
            artifact['stage'] = 'frameworks'
            if artifact['kind']=='assembly_plan':
                artifact['kind'] = 'concept'
        self.refresh_conformance()
        for scores in ([1]*5,[20]*5):
            with self.subTest(scores=scores):
                w.submit_review(self.task,self.review(scores))
        self.assertEqual(len(self.task['reviews']),2)

    def test_uncertain_quality_is_explicit_and_cannot_advance(self):
        review = self.review([20]*5)
        review['candidates'][0]['quality_checks']['detail_craft']['status'] = 'uncertain'
        with self.assertRaisesRegex(ValueError,'Unresolved visual quality: detail_craft'):
            w.submit_review(self.task,review)
        review.update(decision='reject',selected=None,rollback_stage='facades')
        review['candidates'][0]['decision'] = 'reject'
        w.submit_review(self.task,review)
        self.assertEqual(self.task['reviews'][-1]['candidates'][0]['quality_checks']['detail_craft']['status'],'uncertain')

    def test_quality_collector_calls_once_and_retains_uncertainty(self):
        calls = []
        def checked_call(label,payload,images,validator):
            calls.append((label,payload,images))
            value = {'decision':'pass', 'answers':[
                {'status':'pass','observation':'offline fixture: '+key} for key in w.QUALITY_CHECKS],
                'failure_modes':['none, offline fixture']}
            value['answers'][0]['status'] = 'uncertain'
            self.assertTrue(validator(value))
            return value
        evidence = {'plan':self.plan,'conformance':self.conformance,'facade_section':{'large':'geometry'},
                    'walls':{'legacy':'geometry'},'openings':[],'structure':{},
                    'observations':{'front':'offline view'},'reference_comparisons':['offline comparison']*5}
        result = a.collect_architectural_verdict(self.task,evidence,checked_call)
        self.assertEqual(result['decision'],'reject')
        self.assertNotIn('scores',result)
        self.assertNotIn('answers',result)
        self.assertEqual(result['quality_checks']['style_character']['status'],'uncertain')
        self.assertEqual(set(result['quality_checks']),set(w.QUALITY_CHECKS))
        self.assertEqual(len(calls),1)
        label,payload,images = calls[0]
        self.assertEqual(label,'quality')
        self.assertEqual(images,[])
        self.assertFalse(set(payload) & {'facade_section','walls','openings','structure'})
        self.assertEqual(payload['question_order'],list(w.QUALITY_CHECKS))
        self.assertEqual(set(payload['required_output']),{'decision','answers','failure_modes'})
        self.assertEqual(len(payload['required_output']['answers']),6)
        self.assertTrue(all(set(answer)=={'status','observation'} for answer in payload['required_output']['answers']))

    def test_quality_collector_rejects_missing_answers_and_misplaced_findings(self):
        base = {'decision':'pass', 'answers':[
            {'status':'pass','observation':'offline fixture: '+key} for key in w.QUALITY_CHECKS],
            'failure_modes':['none, offline fixture']}
        missing_answers = deepcopy(base)
        missing_answers.pop('answers')
        missing_answers['quality_checks'] = self.review()['candidates'][0]['quality_checks']
        five_answers = deepcopy(base)
        five_answers['answers'].pop()
        findings_as_seventh_answer = deepcopy(base)
        findings_as_seventh_answer['answers'].append({'failure_modes':['misplaced fixture finding']})
        nested_only_findings = deepcopy(base)
        nested_only_findings.pop('failure_modes')
        nested_only_findings['answers'][-1]['failure_modes'] = ['misplaced fixture finding']
        for name,value in [('missing answers',missing_answers),('five answers',five_answers),
                           ('seventh answer',findings_as_seventh_answer),('nested-only findings',nested_only_findings)]:
            with self.subTest(shape=name):
                def checked_call(label,payload,images,validator):
                    validator(value)
                    return value
                with self.assertRaises(ValueError):
                    a.collect_architectural_verdict(self.task,{'plan':self.plan,'conformance':self.conformance},checked_call)


if __name__ == '__main__':
    unittest.main()
