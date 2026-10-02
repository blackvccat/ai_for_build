"""Candidate retention tests use synthetic artifacts, never game acceptance."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from paris_builder import candidate_search as search, workflow as w
from paris_builder.operations import write_json


class CandidateSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.task = w.create_task(self.root / 'workflow.json',
            {'style': 'Paris', 'use': 'housing', 'scale_budget': {}, 'views': list(w.VIEWS),
             'minecraft_version': '1.21.11', 'data_version': 4671}, 'fixture', {'image_input': True})
        self.task.update(stage='facades', intent={'storeys': 2}, selected={}, review_policy='layered-v2')
        module = 'def build():\n    return "fixture"\n'
        files = {'design.py': hashlib.sha256(module.encode()).hexdigest()}
        ident = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
        version = self.root / 'generator-versions' / ident
        version.mkdir(parents=True)
        (version / 'design.py').write_text(module, encoding='utf-8', newline='\n')
        write_json(version / 'version.json', {'id': ident, 'files': files})
        self.generator = {'id': ident, 'path': str(version)}

    def tearDown(self):
        self.tmp.cleanup()

    def candidate(self, revision, failures=(), score=80, na=(), content=None):
        self.task.update(revision=revision, stage='facades', artifacts=[], generator_version=self.generator)
        folder = self.root / ('revision-' + str(revision)) / 'facades' / 'facade-1'
        folder.mkdir(parents=True)
        schematic = folder / 'candidate.schem'
        schematic.write_bytes(content or ('synthetic-%d' % revision).encode())
        image = folder / 'previews' / 'front.png'
        image.parent.mkdir()
        image.write_bytes(b'fixture-image')
        plan = {'form': 'corner_house', 'width': 24, 'depth': 30, 'storeys': 2,
                'roof_height': 9, 'chamfer': 6}
        values = {'schematic': None, 'assembly_plan': plan,
                  'technical_validation': {'status': 'PASS', 'generator_version': self.generator},
                  'views': {'front': {'path': str(image), 'sha256': w.sha(image)}}}
        for kind, data in values.items():
            path = schematic if kind == 'schematic' else folder / (kind + '.json')
            if data is not None:
                write_json(path, data)
            w.register_artifact(self.task, kind, path, candidate='facade-1',
                                **({'view_set': 'reduced'} if kind == 'views' else {}))
        write_json(folder / 'manifest.json', {'plan': plan})
        write_json(folder / 'facade_section.json', {'source': {'path': str(schematic),
                                                               'sha256': w.sha(schematic)}})
        def item(key):
            return {'status': 'fail' if key in failures else 'not_applicable' if key in na else 'pass',
                    'observation': 'Synthetic fixture observation'}
        row = {'id': 'facade-1', 'decision': 'reject', 'scores': [score / 5] * 5,
               'layer_checks': {k: item('layer_checks/' + k) for k in w.LAYER_CHECKS},
               'detail_checks': {g: {k: item('detail_checks/' + g + '/' + k) for k in w.DETAIL_CHECKS}
                                 for g in w.LAYER_CHECKS[:5]},
               'storey_checks': {str(i): {k: item('storey_checks/' + str(i) + '/' + k)
                                        for k in w.DETAIL_CHECKS} for i in range(2)}}
        review = {'stage': 'facades', 'revision': revision, 'artifact_hashes': w.bindings(self.task),
                  'decision': 'reject', 'reviewer': 'fixture', 'rationale': 'Synthetic test rejection',
                  'candidates': [row]}
        self.task['reviews'].append(review)
        return review, schematic, plan

    def conformance(self, schematic, plan, statuses):
        return {'version': 1, 'policy_id': 'fixture-geometry', 'stage': 'facades',
                'source': {'path': str(schematic), 'sha256': w.sha(schematic)},
                'plan_sha256': search._identity(plan),
                'checks': [{'id': key, 'status': value, 'required': True,
                            'observation': 'Synthetic measured geometry'} for key, value in statuses.items()]}

    def test_better_geometry_survives_higher_score_and_history_rejection(self):
        best, _, _ = self.candidate(59, ['layer_checks/roof'], 70)
        first = search.retain_review(self.task, best)['best']['facades:historical-v1']
        worse, _, _ = self.candidate(71, ['layer_checks/roof', 'layer_checks/corner'], 95)
        current = search.retain_review(self.task, worse)['best']['facades:historical-v1']
        self.assertEqual(first['snapshot_id'], current['snapshot_id'])
        retained = search.verify(self.task, first['snapshot_id'])
        self.assertEqual(retained['original_review']['decision'], 'reject')
        self.assertIsNone(retained['metric']['feasible'])

    def test_unverified_na_and_missing_checks_do_not_improve_retained_candidate(self):
        review, _, _ = self.candidate(1, ['layer_checks/roof'], 70)
        incumbent = search.retain_review(self.task, review)['best']['facades:historical-v1']
        gaming, _, _ = self.candidate(2, score=99, na=['layer_checks/roof'])
        candidate = search.retain_review(self.task, gaming)['best']['facades:historical-v1']
        self.assertEqual(candidate['snapshot_id'], incumbent['snapshot_id'])
        missing, _, _ = self.candidate(3, score=100)
        missing['candidates'][0]['layer_checks'].pop('roof')
        candidate = search.retain_review(self.task, missing)['best']['facades:historical-v1']
        self.assertEqual(candidate['snapshot_id'], incumbent['snapshot_id'])

    def test_restore_copies_hash_bound_design_into_new_revision_without_approval(self):
        review, schematic, _ = self.candidate(59, ['layer_checks/roof'], 86)
        best = search.retain_review(self.task, review)['best']['facades:historical-v1']
        original = deepcopy(self.task)
        # Original files may subsequently disappear; retained bytes remain authoritative.
        schematic.unlink()
        restored = search.restore(self.task, snapshot_id=best['snapshot_id'])
        self.assertEqual(self.task, original)
        self.assertEqual(restored['revision'], 60)
        self.assertEqual(restored['reviews'], original['reviews'])
        self.assertEqual(restored['candidate_restoration']['original_decision'], 'reject')
        self.assertEqual(restored['candidate_restoration']['approval'], 'RE_REVIEW_REQUIRED')
        self.assertEqual(restored['game_acceptance'], 'PENDING')
        self.assertEqual(restored['awaiting'], 'VISUAL_REVIEW')
        w._check_hashes(restored)
        restored_schem = next(a for a in restored['artifacts'] if a['kind'] == 'schematic')
        self.assertEqual(restored_schem['sha256'], best_review_sha := review['artifact_hashes'][str(schematic)])
        self.assertEqual(w.sha(restored_schem['path']), best_review_sha)
        technical = json.loads(next(Path(a['path']).read_text(encoding='utf-8')
                                    for a in restored['artifacts'] if a['kind'] == 'technical_validation'))
        self.assertEqual(technical['generator_version'], restored['generator_version'])
        with self.assertRaisesRegex(ValueError, 'Stale review'):
            w.validate_review(restored, review)

    def test_snapshot_and_blob_tampering_block_restore_before_new_files_exist(self):
        review, _, _ = self.candidate(1)
        entry = search.retain_review(self.task, review)['best']['facades:historical-v1']
        body = search.verify(self.task, entry['snapshot_id'])
        blob = self.root / 'candidate-search' / body['files'][0]['stored_path']
        blob.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'evidence changed'):
            search.restore(self.task, snapshot_id=entry['snapshot_id'])
        self.assertFalse((self.root / 'revision-2').exists())

    def test_review_binding_tampering_never_enters_search(self):
        review, schematic, _ = self.candidate(1)
        schematic.write_bytes(b'changed-before-retention')
        with self.assertRaisesRegex(ValueError, 'Changed or missing'):
            search.retain_review(self.task, review)
        self.assertEqual(search.summary(self.task)['candidates_retained'], 0)

    def test_generator_content_identity_cannot_be_rewritten_under_original_version(self):
        review, _, _ = self.candidate(1)
        version = Path(self.generator['path'])
        module = version / 'design.py'
        module.write_text('def build():\n    return "changed"\n', encoding='utf-8')
        metadata = json.loads((version / 'version.json').read_text(encoding='utf-8'))
        metadata['files']['design.py'] = w.sha(module)
        write_json(version / 'version.json', metadata)
        with self.assertRaisesRegex(ValueError, 'generator identity changed'):
            search.retain_review(self.task, review)

    def test_deterministic_repair_cannot_regress_a_previously_passed_obligation(self):
        review, schematic, plan = self.candidate(1, score=70)
        evidence = self.conformance(schematic, plan, {'roof': 'fail', 'corner': 'pass', 'openings': 'pass'})
        incumbent = search.retain_review(self.task, review,
            conformance_by_candidate={'facade-1': evidence})['best']['facades:conformance-v1']
        repaired, schematic, plan = self.candidate(2, score=99)
        evidence = self.conformance(schematic, plan, {'roof': 'pass', 'corner': 'unsupported', 'openings': 'pass'})
        result = search.retain_review(self.task, repaired, conformance_by_candidate={'facade-1': evidence})
        self.assertEqual(result['best']['facades:conformance-v1']['snapshot_id'], incumbent['snapshot_id'])
        index = json.loads((self.root / 'candidate-search' / 'index.json').read_text(encoding='utf-8'))
        self.assertTrue(any(e['regressions'] == ['corner'] for e in index['candidates'].values()))
        corrected, schematic, plan = self.candidate(3, score=60)
        evidence = self.conformance(schematic, plan, {'roof': 'pass', 'corner': 'pass', 'openings': 'pass'})
        best = search.retain_review(self.task, corrected,
            conformance_by_candidate={'facade-1': evidence})['best']['facades:conformance-v1']
        self.assertEqual(best['original_revision'], 3)
        self.assertTrue(best['metric']['feasible'])

    def test_conformance_must_bind_current_export_and_plan(self):
        review, schematic, plan = self.candidate(1)
        evidence = self.conformance(schematic, plan, {'roof': 'pass'})
        evidence['source']['sha256'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'different export'):
            search.retain_review(self.task, review, conformance_by_candidate={'facade-1': evidence})
        evidence = self.conformance(schematic, plan, {'roof': 'pass'})
        evidence['plan_sha256'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'different plan'):
            search.retain_review(self.task, review, conformance_by_candidate={'facade-1': evidence})

    def test_default_restore_uses_incumbent_even_when_regressing_candidate_has_better_rank(self):
        review, schematic, plan = self.candidate(1, score=70)
        evidence = self.conformance(schematic, plan, {'roof': 'fail', 'corner': 'pass', 'openings': 'fail'})
        incumbent = search.retain_review(self.task, review,
            conformance_by_candidate={'facade-1': evidence})['best']['facades:conformance-v1']
        regression, schematic, plan = self.candidate(2, score=99)
        evidence = self.conformance(schematic, plan, {'roof': 'pass', 'corner': 'fail', 'openings': 'pass'})
        search.retain_review(self.task, regression, conformance_by_candidate={'facade-1': evidence})
        restored = search.restore(self.task)
        self.assertEqual(restored['candidate_restoration']['snapshot_id'], incumbent['snapshot_id'])
        self.assertEqual(restored['candidate_restoration']['source_revision'], 1)

    def test_quality_failures_outrank_descriptive_scores_and_ties_retain_incumbent(self):
        review, schematic, plan = self.candidate(1, score=70)
        review['candidates'][0]['quality_checks'] = {k: {'status': 'pass', 'observation': 'Fixture visual quality'}
                                                   for k in w.QUALITY_CHECKS}
        evidence = self.conformance(schematic, plan, {'roof': 'pass'})
        incumbent = search.retain_review(self.task, review,
            conformance_by_candidate={'facade-1': evidence})['best']['facades:conformance-v1']
        worse, schematic, plan = self.candidate(2, score=99)
        worse['candidates'][0]['quality_checks'] = deepcopy(review['candidates'][0]['quality_checks'])
        worse['candidates'][0]['quality_checks']['detail_craft']['status'] = 'fail'
        evidence = self.conformance(schematic, plan, {'roof': 'pass'})
        current = search.retain_review(self.task, worse,
            conformance_by_candidate={'facade-1': evidence})['best']['facades:conformance-v1']
        self.assertEqual(current['snapshot_id'], incumbent['snapshot_id'])
        equal, schematic, plan = self.candidate(3, score=100)
        equal['candidates'][0]['quality_checks'] = deepcopy(review['candidates'][0]['quality_checks'])
        evidence = self.conformance(schematic, plan, {'roof': 'pass'})
        current = search.retain_review(self.task, equal,
            conformance_by_candidate={'facade-1': evidence})['best']['facades:conformance-v1']
        self.assertEqual(current['snapshot_id'], incumbent['snapshot_id'])

    def test_persistent_design_identity_and_shared_blobs_across_multiple_reviews(self):
        review, _, _ = self.candidate(1)
        first = search.retain_review(self.task, review)['best']['facades:historical-v1']
        folder = self.root / 'candidate-search' / 'blobs'
        count = len(list(folder.iterdir()))
        revised_review = deepcopy(review)
        revised_review['candidates'][0]['scores'] = [19] * 5
        result = search.retain_review(self.task, revised_review)
        second = result['best']['facades:historical-v1']
        self.assertEqual(first['candidate_id'], second['candidate_id'])
        self.assertNotEqual(first['snapshot_id'], second['snapshot_id'])
        self.assertEqual(result['candidates_retained'], 2)
        self.assertEqual(len(list(folder.iterdir())), count)

    def test_historical_import_reports_missing_evidence_and_preserves_valid_best(self):
        old, schematic, _ = self.candidate(1)
        schematic.unlink()
        best, _, _ = self.candidate(59, ['layer_checks/roof'], 86)
        result = search.import_history(self.task, min_revision=1)
        self.assertEqual(result['best']['facades:historical-v1']['original_revision'], 59)
        self.assertEqual(result['skipped'][0]['revision'], 1)


if __name__ == '__main__':
    unittest.main()
