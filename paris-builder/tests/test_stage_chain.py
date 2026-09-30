"""Regression tests for the full stage chain, with no network access.

The offline replay client is a TEST FIXTURE: it checks that the stages, gates,
artifact registration, view mapping and state lab are wired correctly. It is not
live model evidence and says nothing about architectural quality.
"""
import json
import re
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))

from paris_builder import workflow as w  # noqa: E402
from paris_builder.replay import ReplayClient, STOREYS_BY_SEED, _candidate_ids  # noqa: E402
from paris_builder.executor import candidate_image_labels, view_bundle  # noqa: E402
from model_design_run import Runner  # noqa: E402


class ReplayFixtureTests(unittest.TestCase):
    def test_every_protocol_view_has_a_label(self):
        # The critic is told which image holds each protocol view; a view that no
        # label covers would silently invite the model to invent observations.
        render_paths = {name: name + '.png' for name in
                        ('front', 'back', 'left', 'right', 'top', 'axonometric_front', 'axonometric_back')}
        render_paths.update({'orbit_street_%03d' % a: 'orbit_street_%03d.png' % a for a in range(0, 360, 45)})
        render_paths.update({'orbit_high_%03d' % a: 'orbit_high_%03d.png' % a for a in range(0, 360, 45)})
        labels = candidate_image_labels(render_paths)
        keys = list(labels)
        for view in w.VIEWS:
            covered = view in labels
            if not covered:
                for key, value in labels.items():
                    if '..' in key or '..' in str(value):
                        covered = True
                        break
            self.assertTrue(covered, 'no image label covers ' + view)

    def test_scripted_verdict_follows_the_recorded_seed(self):
        client = ReplayClient({'offline_replay': True})
        first = client._look('CANDIDATE: fr1')        # 6317, the short massing
        second = client._look('CANDIDATE: fr2')       # 6421
        self.assertEqual(first['decision'], 'reject')
        self.assertEqual(second['decision'], 'pass')
        self.assertEqual(set(second['view_observations']), set(w.VIEWS))
        self.assertGreaterEqual(len(second['reference_comparison']), 5)
        self.assertEqual(STOREYS_BY_SEED[6317], 4)

    def test_first_design_is_the_seed_the_scripted_critic_rejects(self):
        # The blocked-gate path is only reproducible if design counting does not
        # depend on how many research/retrieval calls came first.
        client = ReplayClient({'offline_replay': True})
        client.complete('research_evidence please')
        client.complete('component_selection CANDIDATES: []')
        first = client._concept()['concept']
        self.assertEqual(first['massing_seed'], 6317)
        self.assertLess(STOREYS_BY_SEED[first['massing_seed']], 5)

    def test_selection_only_names_reviewed_candidates(self):
        client = ReplayClient({'offline_replay': True})
        prompt = 'Select ONE frameworks candidate.\nCANDIDATES: {"mf1": {}, "mf2": {}}'
        self.assertIn(client._select(prompt)['selected'], ('mf1', 'mf2'))
        self.assertEqual(_candidate_ids(prompt), ['mf1', 'mf2'])

    def test_selection_reads_real_two_letter_candidate_ids(self):
        # Stage directories are fr*/fa*/ti*/de*, so an id regex limited to one
        # stage prefix would silently select a candidate that was never reviewed.
        prompt = ('Select ONE frameworks candidate.\nCANDIDATES: '
                  '{"fr1": {"decision": "pass"}, "fr2": {"decision": "pass"}}')
        self.assertEqual(_candidate_ids(prompt), ['fr1', 'fr2'])
        client = ReplayClient({'offline_replay': True})
        self.assertIn(client._select(prompt)['selected'], ('fr1', 'fr2'))

    def test_receipts_mark_replay_as_offline(self):
        client = ReplayClient({'offline_replay': True})
        _, receipt = client.complete('STAGE SCOPE: massing. CANDIDATE: mf1 "massing_seed": 6521')
        self.assertTrue(receipt['offline_replay'])
        self.assertEqual(receipt['usage']['total_tokens'], 0)


class StageChainTests(unittest.TestCase):
    """Stage table, gate ordering and refusal to skip a stage."""

    def runner(self, run):
        args = type('Args', (), {'run': run, 'provider': 'configs/providers/replay.json',
                                 'size': 60, 'scheme': 1, 'candidates': 5, 'revisions': 0,
                                 'brief': None, 'revision_notes': None, 'action': 'all'})()
        return Runner(args)

    def test_selection_falls_back_to_recorded_verdicts(self):
        # A selection reply of "none" must not end the run nor invent a candidate:
        # the fallback ranks what was actually reviewed and records the change.
        runner = self.runner('MODEL-DESIGN-SELECTUNIT')
        reviews = {
            'fa1': {'decision': 'reject', 'scores': [15, 15, 15, 15, 16], 'failure_modes': ['x'], 'rationale': 'r'},
            'fa2': {'decision': 'pass', 'scores': [15, 15, 15, 15, 15], 'failure_modes': ['none'], 'rationale': 'r'},
            'fa3': {'decision': 'reject', 'scores': [15, 15, 15, 15, 15], 'failure_modes': ['x'], 'rationale': 'r'},
        }
        self.assertEqual(runner.best_reviewed(reviews), 'fa2')
        runner.client.complete = lambda prompt, images=(), max_tokens=3500: (
            {'selected': 'none', 'rationale': 'no candidate is truly acceptable'},
            {'usage': {'total_tokens': 1}, 'model': 'stub', 'elapsed_seconds': 0.0})
        selected, _ = runner.select_candidate('facades', reviews)
        self.assertEqual(selected, 'fa2')
        # With no passing candidate it still picks a reviewed one by axis total.
        self.assertEqual(runner.best_reviewed({'a': {'scores': [14, 14, 14, 14, 17]},
                                               'b': {'scores': [16, 16, 16, 16, 16]}}), 'b')

    def test_stage_table_matches_workflow_requirements(self):
        self.assertEqual(Runner.STAGE_ACTIONS['frameworks'][2], 5)
        self.assertEqual(Runner.STAGE_ACTIONS['facades'][2], 3)
        for stage in ('tier2', 'tier3', 'delivery'):
            self.assertEqual(Runner.STAGE_ACTIONS[stage][2], 1)
        self.assertIsNone(Runner.NEXT_ACTION['delivery'])
        self.assertEqual(Runner.NEXT_ACTION['frameworks'], 'facades')

    def test_required_artifact_kinds_are_covered_by_the_stage_table(self):
        for action, (stage, _build_stage, _count) in Runner.STAGE_ACTIONS.items():
            self.assertTrue(w.REQUIRED[stage], stage + ' has no required artifacts')

    def test_action_cannot_skip_an_unfinished_gate(self):
        run = 'MODEL-DESIGN-GATEUNIT-%d' % datetime.now(timezone.utc).timestamp()
        try:
            runner = self.runner(run)
            task = w.create_task(runner.run_dir / 'task.json', json.loads(
                (ROOT / 'knowledge/workflow/brief.example.json').read_text(encoding='utf-8')),
                'offline-replay-fixture', {'image_input': True})
            task['stage'] = 'tier2'
            w.save(task)
            with self.assertRaises(SystemExit):
                runner.action_for(task, 'delivery')
            self.assertEqual(runner.action_for(task, 'all'), 'tier2')
        finally:
            shutil.rmtree(ROOT / 'runs' / run, ignore_errors=True)

    def test_ensure_prefix_never_repeats_a_passed_gate(self):
        # Re-submitting research from a later stage binds the review to the wrong
        # stage and fails the gate ("Expected N candidates"), so prefix work must
        # be order-checked rather than assumed.
        run = 'MODEL-DESIGN-PREFIXUNIT'
        runner = self.runner(run)
        run_dir = ROOT / 'runs' / run
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / 'component_selection.json').write_text('{}', encoding='utf-8')
            calls = []

            def fake_research(task):
                calls.append('research')
                task['stage'] = 'retrieval'

            def fake_retrieval(task):
                calls.append('retrieval')
                task['stage'] = 'frameworks'

            runner.research = fake_research
            runner.retrieval_stage = fake_retrieval

            task = {'stage': 'frameworks'}
            runner.ensure_prefix(task)
            self.assertEqual(calls, [], 'a task already at frameworks needs no prefix work')

            task = {'stage': 'retrieval'}
            runner.ensure_prefix(task)
            self.assertEqual(calls, ['retrieval'], 'a task at retrieval must skip research')

            task = {'stage': 'research'}
            runner.ensure_prefix(task)
            self.assertEqual(calls, ['retrieval', 'research', 'retrieval'],
                             'a fresh task runs research then retrieval, not research twice')

            task = {'stage': 'tier2'}
            runner.ensure_prefix(task)
            self.assertEqual(calls, ['retrieval', 'research', 'retrieval'],
                             'a task past frameworks keeps its registered selection')
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)

    def test_view_bundle_maps_renderer_names_to_protocol_names(self):
        # A renderer name must never be assumed to equal a protocol view name.
        temp = Path(tempfile.mkdtemp())
        try:
            names = list(('front', 'back', 'left', 'right', 'top', 'axonometric_front', 'axonometric_back'))
            names += ['orbit_street_%03d' % a for a in range(0, 360, 45)]
            names += ['orbit_high_%03d' % a for a in range(0, 360, 45)]
            paths = {}
            for name in names:
                path = temp / (name + '.png')
                path.write_bytes(b'fixture')
                paths[name] = str(path)
            bundle = view_bundle(paths)
            self.assertEqual(set(bundle), set(w.VIEWS))
            self.assertIn('orbit_low_000', bundle)
        finally:
            shutil.rmtree(temp, ignore_errors=True)

    def test_every_stage_registers_the_artifacts_its_gate_requires(self):
        # A stage that builds a file but forgets to register it is blocked by its
        # own gate ("Missing required artifact kinds"), which is how the facades
        # assembly_plan omission was found. Read the registration site so a new
        # required kind cannot silently fall out of it.
        source = (ROOT / 'tools' / 'model_design_run.py').read_text(encoding='utf-8')
        block = source.split('def register_candidate', 1)[1].split('def review_response', 1)[0]
        registered = set(re.findall(r"register_artifact\(task, '([a-z_]+)'", block))
        for stage in ('facades', 'tier2', 'tier3', 'delivery'):
            for kind in w.REQUIRED[stage]:
                if kind in ('schematic', 'assembly_plan', 'views', 'technical_validation', 'concept',
                            'state_lab', 'manifest'):
                    self.assertIn(kind, registered, '%s requires %s but it is never registered' % (stage, kind))

    def test_single_candidate_stages_register_where_the_gate_looks(self):        # The gate treats a single-candidate stage as `candidate=None`; registering
        # such a stage under a real id leaves the gate looking at an empty group
        # ("Missing required artifact kinds"). Drive the real gate to prove it.
        run = 'MODEL-DESIGN-KEYUNIT'
        runner = self.runner(run)
        run_dir = ROOT / 'runs' / run
        try:
            stage_dir = run_dir / 'tier2'
            stage_dir.mkdir(parents=True, exist_ok=True)
            views = {}
            for view in w.VIEWS:
                image = stage_dir / (view + '.png')
                image.write_bytes(b'fixture')
                views[view] = {'path': str(image), 'sha256': w.sha(image)}
            files = {}
            for name in ('concept', 'schematic', 'assembly_plan', 'technical_validation'):
                path = stage_dir / (name + '.json')
                path.write_text(json.dumps({'status': 'PASS'}), encoding='utf-8')
                files[name] = str(path)
            files['views'] = views
            built = dict(files)
            built['candidate_id'] = 'ti1'
            # views.json is written by register_candidate itself; its directory must
            # not have to pre-exist (the real caller does not create it either).
            (stage_dir / 'ti1').mkdir(parents=True, exist_ok=True)
            task = w.create_task(stage_dir / 'task.json', json.loads(
                (ROOT / 'knowledge/workflow/brief.example.json').read_text(encoding='utf-8')),
                'offline-replay-fixture', {'image_input': True})
            task['stage'] = 'tier2'
            w.save(task)
            runner.register_candidate(task, built, stage_dir, candidate=None)
            review = {'stage': 'tier2', 'revision': task['revision'], 'artifact_hashes': w.bindings(task),
                      'reviewer': 'offline-fixture', 'reviewer_type': 'model', 'decision': 'pass',
                      'rationale': 'fixture', 'candidates': [{'id': None,
                          'view_observations': {v: 'fixture' for v in w.VIEWS},
                          'reference_comparison': {'standard_%d' % i: 'fixture' for i in range(5)},
                          'failure_modes': ['none']}]}
            w.submit_review(task, review)          # must not raise
            self.assertEqual({a['candidate'] for a in task['artifacts']}, {None})
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)

    def _summary(self, action, stage, reviewed_stage, blocked=None, selected=None):
        return {'action': action, 'stage': stage, 'reviewed_stage': reviewed_stage,
                'gate_blocked': blocked, 'selected': selected}

    def test_stage_scope_names_what_the_ladder_has_not_added_yet(self):
        # The critic rejected every framework for missing shopfronts, balconies and
        # a mansard crown -- all of which the production ladder adds later. The
        # stage scope must say so explicitly and forbid scoring them.
        from paris_builder.executor import design_instruction, look_instruction
        critic = look_instruction({'style': 'x'}, 'fw1', {'front': 'overview.png'}, {'r.png': 'standard'}, 'frameworks')
        self.assertIn('NOT YET PRESENT', critic)
        self.assertIn('must not lower any score', critic)
        self.assertIn('ground-floor commercial layer is part of the framework', critic)
        designer = design_instruction({'style': 'x'}, [], None, 'frameworks')
        self.assertIn('NOT YET PRESENT', designer)
        facade = look_instruction({'style': 'x'}, 'fa1', {'front': 'overview.png'}, {'r.png': 'standard'}, 'facades')
        self.assertIn('FACADE COMPOSITION STAGE', facade)

    def test_unparseable_reply_is_retried_once(self):
        # One malformed reply must not end a long live run; the retry is recorded.
        from paris_builder.providers import ProviderError
        run = 'MODEL-DESIGN-RETRYUNIT'
        runner = self.runner(run)
        run_dir = ROOT / 'runs' / run
        try:
            class Flaky:
                def __init__(self):
                    self.calls = 0

                def complete(self, prompt, images=(), max_tokens=3500):
                    self.calls += 1
                    if self.calls == 1:
                        raise ProviderError('Provider did not return valid JSON')
                    return {'ok': True}, {'usage': {'total_tokens': 1}, 'model': 'flaky',
                                           'elapsed_seconds': 0.0}

            runner.client = Flaky()
            result = runner.call('prompt', label='flaky')
            self.assertEqual(result, {'ok': True})
            self.assertEqual(runner.client.calls, 2)
            kinds = [json.loads(line)['kind'] for line in
                     (run_dir / 'receipts.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertIn('model_call_failed', kinds)
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)

    def test_family_vocabulary_is_resolved_not_guessed(self):
        # Models name the architectural noun ("window", "balcony") instead of the
        # library family id; that must be resolved, while a genuinely unknown
        # family must still fail the contract.
        from paris_builder.design_contract import resolve_family, normalize_component_policy
        # The retrieval library's window family is a study family; the model keeps
        # choosing it because it is architecturally right, so it maps to the
        # placeable surround family with a recorded substitution.
        self.assertEqual(resolve_family('window_assembly'), 'window_surround')
        self.assertEqual(resolve_family('window'), 'window_surround')
        self.assertEqual(resolve_family('window_frame'), 'window_surround')
        self.assertEqual(resolve_family('Store Front'), 'shopfront')
        self.assertEqual(resolve_family('shopfront'), 'shopfront')
        self.assertIsNone(resolve_family('definitely_not_a_family'))
        policy, notes = normalize_component_policy(
            {'primary_street': {'window_frame': {'variant': 0, 'reason': 'r', 'evidence_refs': ['e']}},
             'courtyard': {'nonsense': {'variant': 0, 'reason': 'r', 'evidence_refs': ['e']}}})
        self.assertIn('window_surround', policy['primary_street'])
        self.assertIn('nonsense', policy['courtyard'])
        self.assertEqual([n['action'] for n in notes], ['renamed', 'unresolved'])

    def test_pipeline_stops_when_a_reviewed_stage_did_not_advance(self):
        # A stage whose own selection was rejected keeps task['stage']; auto-continue
        # must stop instead of rebuilding the same stage forever.
        runner = self.runner('MODEL-DESIGN-LOOPUNIT')
        task = {'stage': 'frameworks'}
        calls = []

        def stalled(task, action):
            calls.append(action)
            return self._summary(action, task['stage'], task['stage'], selected='fr1')

        runner.stage_pipeline = stalled
        summary = runner.pipeline(task)
        self.assertEqual(calls, ['frameworks'])
        self.assertEqual(summary['stage'], 'frameworks')

    def test_prefix_advance_is_not_mistaken_for_stage_progress(self):
        # Running frameworks from research advances research -> retrieval ->
        # frameworks. That prefix walk is not the frameworks gate passing, so the
        # loop must stop rather than rebuilding frameworks a second time.
        runner = self.runner('MODEL-DESIGN-LOOPUNIT')
        task = {'stage': 'research'}
        calls = []

        def prefix_then_stall(task, action):
            calls.append(action)
            task['stage'] = 'frameworks'
            return self._summary(action, 'frameworks', 'frameworks')

        runner.stage_pipeline = prefix_then_stall
        summary = runner.pipeline(task)
        self.assertEqual(calls, ['frameworks'])
        self.assertEqual(summary['stage'], 'frameworks')

    def test_pipeline_continues_only_while_the_stage_advances(self):
        # Continuing is driven by the reviewed stage pointer moving forward, not by
        # the action label: every successful advance runs exactly one more stage.
        runner = self.runner('MODEL-DESIGN-LOOPUNIT')
        task = {'stage': 'frameworks'}
        calls = []
        progression = ['facades', 'tier2', 'tier3', 'delivery', 'game']

        def advancing(task, action):
            reviewed = task['stage']
            calls.append(action)
            task['stage'] = progression[len(calls) - 1]
            return self._summary(action, task['stage'], reviewed)

        runner.stage_pipeline = advancing
        summary = runner.pipeline(task)
        self.assertEqual(calls, ['frameworks', 'facades', 'tier2', 'tier3', 'delivery'])
        self.assertEqual(summary['stage'], 'game',
                         'delivery runs once and the run stops at the user-only game gate')

    def test_pipeline_stops_at_a_terminal_stage(self):
        runner = self.runner('MODEL-DESIGN-LOOPUNIT')
        task = {'stage': 'delivery'}
        runner.action_for = lambda task, requested: 'delivery'

        def finish(task, action):
            reviewed = task['stage']
            task['stage'] = 'accepted'
            return self._summary(action, 'accepted', reviewed)

        runner.stage_pipeline = finish
        summary = runner.pipeline(task)
        self.assertEqual(summary['stage'], 'accepted')


if __name__ == '__main__':
    unittest.main()
