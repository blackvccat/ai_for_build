#!/usr/bin/env python3
"""Drive a bounded model design cycle through every evidence-gated stage.

Stages run in one direction only: research -> retrieval -> frameworks (5
competitors) -> facades (3 competitors) -> tier2 -> tier3 -> delivery. Each
visual stage must register real per-view observations and can only advance when
the gate evidence validates; a rejected stage stays put and records the block.
This tool never closes the game gate, never treats model text as executable
code, and never treats a package as user acceptance.

Use `--provider configs/providers/replay.json` for a deterministic, no-network
replay of the whole chain (test fixture, not live model evidence).
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from paris_builder import workflow as w  # noqa: E402
from paris_builder.executor import (build_candidate, candidate_image_labels,  # noqa: E402
                                    candidate_images, delivery_evidence, design_instruction,
                                    expected_views, look_instruction, normalize_rollback,
                                    normalize_view_observations, retrieval_payload, state_lab)
from paris_builder.providers import MultimodalClient, ProviderError  # noqa: E402
from paris_builder.retrieval import ComponentIndex  # noqa: E402
from paris_builder.design_contract import validate_concept  # noqa: E402
from paris_builder.components import FAMILIES  # noqa: E402

QUERIES = [
    '街面店面、招牌带与雨棚', '窗套、窗台与窗楣', '阳台板、栏杆与栏板',
    '檐口、女儿墙与层间带', '转角石、壁柱与隅石', '屋顶老虎窗、烟囱与排水沟',
    '内院回折与屋顶交接', '入口门廊与大门',
]


def review_decision(reviews, selected):
    """The gate's decision for the selected candidate: pass only on a real pass."""
    return 'pass' if reviews[selected].get('decision') == 'pass' else 'reject'


class Runner:
    def __init__(self, args):
        self.args = args
        # `--views reduced` renders only the seven fixed views: cheaper for long
        # live pipelines, and recorded as a reduced (non-full) review contract.
        self.orbit = getattr(args, 'views', 'full') != 'reduced'
        self.run_dir = ROOT / 'runs' / args.run
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.config = json.loads((ROOT / args.provider).read_text(encoding="utf-8"))
        # Keep unparseable provider replies inside the run directory for diagnosis.
        self.config.setdefault('raw_reply_dir', str(self.run_dir))
        # An explicit offline_replay provider is a test fixture: it drives the same
        # stage gates without network calls and is recorded as such in receipts.
        if self.config.get('offline_replay'):
            from paris_builder.replay import load_client
            self.client = load_client(self.config)
        else:
            self.client = MultimodalClient(self.config)
        self.index = ComponentIndex(ROOT / 'knowledge/retrieval')
        self.receipts = []
        self.log_path = self.run_dir / 'receipts.jsonl'

    def log(self, kind, payload):
        entry = {'at': datetime.now(timezone.utc).isoformat(), 'kind': kind, **payload}
        self.receipts.append(entry)
        with self.log_path.open('a', encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + '\n')

    def call(self, prompt, images=(), max_tokens=4000, label=None, parse_retries=1):
        """One bounded model call, with a bounded retry when the reply is not JSON.

        A 4k-character reply occasionally contains an unescaped quote inside a
        string, which no parser can recover. Retrying the same request once keeps
        a long live run from being lost to one bad reply; the retry is recorded so
        it is visible in the receipts rather than hidden.
        """
        attempt = 0
        while True:
            try:
                result, receipt = self.client.complete(prompt, images, max_tokens=max_tokens)
            except ProviderError as error:
                attempt += 1
                self.log('model_call_failed', {'label': label, 'attempt': attempt, 'error': str(error)})
                if attempt > parse_retries:
                    raise
                continue
            self.log('model_call', {'label': label, 'images': [str(p) for p in images],
                                    'usage': receipt['usage'], 'model': receipt['model'],
                                    'elapsed_seconds': receipt['elapsed_seconds'], 'attempt': attempt + 1})
            return result

    def retrieve(self):
        seen, results = {}, []
        for text in QUERIES:
            for r in self.index.query(text, limit=4):
                if r['id'] not in seen:
                    seen[r['id']] = True
                    results.append(r)
        results = sorted(results, key=lambda r: (-r['score'], r['id']))
        payload = retrieval_payload(results)
        path = self.run_dir / 'retrieval_results.json'
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding="utf-8")
        self.log('retrieval', {'queries': QUERIES, 'candidate_count': len(payload),
                               'families': sorted({r['family'] for r in payload})})
        return payload

    def run(self):
        brief = json.loads((ROOT / self.args.brief).read_text(encoding="utf-8")) if self.args.brief else json.loads(
            (ROOT / 'knowledge/workflow/brief.example.json').read_text( encoding="utf-8"))
        task_path = self.run_dir / 'task.json'
        if task_path.exists():
            task = w.load(task_path)
            # Published previews are keyed by their file hashes, so a resumed run
            # must keep rendering at the size those files were produced with.
            recorded = task.get('capabilities', {}).get('render_size')
            if recorded is not None and recorded != self.args.size:
                raise SystemExit('This run was recorded at --size %s; resume with that size '
                                 '(or use a new --run name)' % recorded)
        else:
            task = w.create_task(task_path, brief, self.config['model'], {'image_input': True})
        task.setdefault('capabilities', {})['render_size'] = self.args.size
        # The scoring rule a run is judged by is recorded on the task so evidence
        # always says which rule gated it.
        if self.config.get('score_profile'):
            task['score_profile'] = self.config['score_profile']
        task.setdefault('score_profile', w.DEFAULT_SCORE_PROFILE)
        w.save(task)
        self.log('start', {'model': self.config['model'], 'action': self.args.action,
                           'run': self.args.run, 'provider_verified': True})

        if self.args.action == 'pilot':
            summary = self.pilot(task)
        elif self.args.action == 'frameworks':
            summary = self.frameworks(task)
        else:
            summary = self.pipeline(task)
        (self.run_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary

    def research(self, task):
        style_src = ROOT / 'knowledge/styles/paris_haussmann_v0.1.json'
        style_dst = self.run_dir / 'research' / 'style_model.json'
        style_dst.parent.mkdir(parents=True, exist_ok=True)
        style_dst.write_text(style_src.read_text(encoding="utf-8"))
        w.register_artifact(task, 'style_model', style_dst)
        prompt = '\n'.join([
            'Summarise Paris Haussmann research for a Minecraft production pipeline.',
            'Return ONLY JSON with keys research_evidence and rationale.',
            'research_evidence has sources (at least three, each {url, observations:[..]}),',
            'design_inferences (array) and boundaries (array). Use recognised public sources.',
            'Local style model ranges (evidence only): ' + style_src.read_text( encoding="utf-8")[:1200],
        ])
        out = self.call(prompt, max_tokens=1800, label='research')
        evidence = self.run_dir / 'research' / 'research_evidence.json'
        evidence.write_text(json.dumps(out['research_evidence'], ensure_ascii=False, indent=2) + '\n', encoding="utf-8")
        w.register_artifact(task, 'research_evidence', evidence)
        review = {'stage': task['stage'], 'revision': task['revision'], 'artifact_hashes': w.bindings(task),
                  'reviewer': self.config['model'], 'reviewer_type': 'model', 'decision': 'pass',
                  'rationale': out.get('rationale', '')}
        w.submit_review(task, review)
        w.advance(task)
        self.log('stage', {'name': 'research', 'stage_after': task['stage']})

    def retrieval_stage(self, task):
        payload = self.retrieve()
        results_path = self.run_dir / 'retrieval_results.json'
        w.register_artifact(task, 'retrieval_results', results_path)
        prompt = '\n'.join([
            'Select production components for each face role from the retrieved candidates only.',
            'Return ONLY JSON with keys component_selection, rejected, rationale.',
            'component_selection maps role -> {family: {variant:0|1|2, reason, evidence_refs:[candidate id]}}.',
            'Only families from candidates with placeable=true may be selected; placeable=false (window studies) go in rejected with reasons.',
            'Roles: primary_street, secondary_street, corner, rear_return, service_street, courtyard.',
            'CANDIDATES: ' + json.dumps(payload, ensure_ascii=False),
        ])
        out = self.call(prompt, max_tokens=3500, label='retrieval_selection')
        selection = self.run_dir / 'component_selection.json'
        selection.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding="utf-8")
        w.register_artifact(task, 'component_selection', selection)
        review = {'stage': task['stage'], 'revision': task['revision'], 'artifact_hashes': w.bindings(task),
                  'reviewer': self.config['model'], 'reviewer_type': 'model', 'decision': 'pass',
                  'rationale': out.get('rationale', '')}
        w.submit_review(task, review)
        w.advance(task)
        self.log('stage', {'name': 'retrieval', 'stage_after': task['stage'],
                           'roles': sorted(out.get('component_selection', {}))})
        return out.get('component_selection', {})

    # The framework gate reviews the framework LAYER, which includes the opening
    # grid, shopfront layer and facade bands (production stage 1). Reviewing raw
    # stage-0 massing made every candidate fail for missing shopfronts, balconies
    # and the mansard silhouette -- all of which the ladder adds above stage 0.
    STAGE_ACTIONS = {
        'frameworks': ('frameworks', 1, 5),
        'facades': ('facades', 1, 3),
        'tier2': ('tier2', 2, 1),
        'tier3': ('tier3', 3, 1),
        'delivery': ('delivery', 3, 1),
    }
    # Distinct directory prefixes: framework candidates and facade schemes are
    # different competitions and must not overwrite each other's evidence.
    STAGE_PREFIX = {'frameworks': 'fw', 'facades': 'fa', 'tier2': 'ti', 'tier3': 'ti', 'delivery': 'de'}
    NEXT_ACTION = {'frameworks': 'facades', 'facades': 'tier2', 'tier2': 'tier3',
                   'tier3': 'delivery', 'delivery': None}

    def ensure_prefix(self, task):
        """Take a fresh task as far as frameworks, one real gate at a time.

        Only the missing prefix stages run: re-submitting an already-passed gate
        would bind that review to a stage it no longer belongs to (and fail the
        gate's candidate count). A task already past frameworks keeps its
        registered selection.
        """
        if w.STAGES.index(task['stage']) > w.STAGES.index('frameworks'):
            return json.loads((self.run_dir / 'component_selection.json').read_text(encoding="utf-8"))
        for _ in range(len(w.STAGES)):
            stage = task['stage']
            if stage == 'research':
                self.research(task)
            elif stage == 'retrieval':
                self.retrieval_stage(task)
            elif stage == 'frameworks':
                break
            else:
                raise SystemExit('Unexpected stage while preparing: ' + stage)
        return json.loads((self.run_dir / 'component_selection.json').read_text(encoding="utf-8"))

    def action_for(self, task, requested):
        """Resolve the stage an action drives, refusing to skip a gate."""
        stage = task['stage']
        if stage in ('research', 'retrieval'):
            return 'frameworks'
        if requested in ('all', stage):
            return stage
        raise SystemExit('Task is at stage %s; finish that gate before asking for %s' % (stage, requested))

    def register_candidate(self, task, built, stage_dir, candidate=None):
        """Register one candidate's evidence under the id the gate expects.

        Competitive stages (frameworks 5, facades 3) key artifacts by candidate
        id; single-candidate stages (tier2/tier3/delivery) must register with
        `candidate=None`, because that is the only key the gate looks up for them.
        """
        cid = candidate
        w.register_artifact(task, 'concept', built['concept'], candidate=cid)
        w.register_artifact(task, 'schematic', built['schematic'], candidate=cid)
        w.register_artifact(task, 'technical_validation', built['technical_validation'], candidate=cid)
        # facades/tier2/tier3/delivery require the assembly plan as evidence, so it
        # is registered for every candidate, not only for frameworks.
        w.register_artifact(task, 'assembly_plan', built['assembly_plan'], candidate=cid)
        views_path = stage_dir / (built['candidate_id'] if cid is None else cid) / 'views.json'
        views_path.parent.mkdir(parents=True, exist_ok=True)
        views_path.write_text(json.dumps(built['views'], ensure_ascii=False, indent=2) + '\n', encoding="utf-8")
        # Record which protocol view set these images are, so a reduced review is
        # never mistaken for the full seven-plus-sixteen contract.
        w.register_artifact(task, 'views', views_path, candidate=cid, view_set=built.get('view_set', 'full'))
        if stage_dir.name == 'delivery':
            # The state lab is a delivery-stage artifact: the same file is pasted
            # twice with different update policies in game, so it is registered as
            # evidence of the experiment set, not as proof of suppression.
            state_plots = state_lab(built['scene'], stage_dir)
            evidence = delivery_evidence(built, stage_dir, built.get('concept_data', {}))
            w.register_artifact(task, 'state_lab', stage_dir / 'STATE-LAB.schem', candidate=cid)
            w.register_artifact(task, 'state_lab_tests', stage_dir / 'state_lab_tests.json', candidate=cid)
            w.register_artifact(task, 'manifest', evidence['manifest'], candidate=cid)
            w.register_artifact(task, 'instructions', evidence['instructions'], candidate=cid)
            built['state_plots'] = state_plots
        return cid

    def review_response(self, stage, built, labels):
        """One bounded visual-review call per candidate, recorded verbatim."""
        cid = built['candidate_id']
        references = [p for p in self.reference_paths() if p.exists()]
        out = self.call(look_instruction(self.brief, cid, labels, self.reference_labels(), stage),
                        images=candidate_images(built) + references, max_tokens=8000,
                        label='look_%s_%s' % (stage, cid))
        # A dropped view must not discard an otherwise usable verdict: the missing
        # views are marked as unreported and stay visible in the review document.
        frames = expected_views(labels)
        missing = [view for view in frames if not (out.get('view_observations') or {}).get(view)]
        if missing:
            self.log('look_partial', {'stage': stage, 'candidate': cid, 'missing_views': missing})
        out['view_observations'] = normalize_view_observations(out, frames)
        (Path(built['schematic']).parent / 'look.json').write_text(
            json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding="utf-8")
        self.log('look', {'stage': stage, 'candidate': cid, 'decision': out.get('decision'),
                          'failure_modes': out.get('failure_modes'), 'scores': out.get('scores')})
        return out

    def select_candidate(self, stage, reviews):
        """Pick one reviewed candidate, falling back to the recorded verdicts.

        The selection call sometimes answers "none" or restates a candidate's
        description instead of an id. That must not end a long run, and it must
        not invent a choice either: the fallback ranks the candidates that were
        actually reviewed (a passed candidate first, then the highest axis total)
        and the substitution is recorded in receipts.
        """
        prompt = '\n'.join([
            'Select ONE %s candidate to carry into the next stage. Return ONLY JSON with keys selected, rationale.' % stage,
            'selected must be exactly one of these candidate ids: ' + ', '.join(sorted(reviews)),
            'CANDIDATES: ' + json.dumps({cid: {k: out.get(k) for k in
                ('decision', 'scores', 'failure_modes', 'rationale')} for cid, out in reviews.items()}, ensure_ascii=False),
        ])
        out = self.call(prompt, max_tokens=1500, label=stage + '_selection')
        selected = out.get('selected')
        if selected not in reviews:
            selected = self.best_reviewed(reviews)
            self.log('selection_fallback', {'stage': stage, 'model_answer': out.get('selected'),
                                            'selected': selected,
                                            'criterion': 'passed first, then highest axis total'})
        self.log('select', {'stage': stage, 'selected': selected, 'rationale': out.get('rationale')})
        return selected, out.get('rationale', '')

    @staticmethod
    def best_reviewed(reviews):
        def rank(item):
            cid, out = item
            scores = out.get('scores') or [0]
            passed = 1 if out.get('decision') == 'pass' else 0
            return (passed, sum(s for s in scores if isinstance(s, (int, float))), cid)
        return max(reviews.items(), key=rank)[0]

    def stage_pipeline(self, task, action):
        """Run one evidence-gated stage: build, look, select, submit, maybe advance."""
        stage, build_stage, candidate_count = self.STAGE_ACTIONS[action]
        selection = self.ensure_prefix(task)
        # `ensure_prefix` may have walked research/retrieval; record the stage the
        # gate below is actually reviewed at so the caller can tell whether THIS
        # stage advanced instead of seeing the prefix advance as progress.
        reviewed_stage = task['stage']
        meta = json.loads((self.run_dir / 'retrieval_results.json').read_text(encoding="utf-8"))
        self.brief = task['brief']
        stage_dir = self.run_dir / stage
        stage_dir.mkdir(parents=True, exist_ok=True)
        stage_calls_start = self.client.calls
        variants = self.candidate_concepts(task, self.brief, meta, selection, action, candidate_count)
        built = []
        for index, concept in enumerate(variants):
            candidate_dir = stage_dir / ('%s%d' % (self.STAGE_PREFIX[action], index + 1))
            item = build_candidate(concept, candidate_dir, stage=build_stage, scheme=self.args.scheme,
                                   size=self.args.size, orbit=self.orbit)
            item['concept_data'] = concept
            built.append(item)
            self.log('build', {'stage': stage, 'candidate': item['candidate_id'],
                               'schematic': item['schematic'], 'views': len(item['views']),
                               'view_set': item['view_set']})
        for item in built:
            item['response'] = self.review_response(
                stage, item, candidate_image_labels(item['render_paths'], reduced=not self.orbit))
        reviews = {item['candidate_id']: item['response'] for item in built}
        selected, selection_rationale = self.select_candidate(stage, reviews)
        # A stage that rejected every candidate (or rejected its own selection) does
        # not advance; it is re-designed with the recorded failure modes fed back,
        # within the explicit --attempts bound and the provider call budget.
        attempt = 1
        stage_call_budget = self.config.get('max_stage_calls', 24)
        while (review_decision(reviews, selected) != 'pass' and attempt < self.args.attempts
               and (self.client.calls - stage_calls_start) < stage_call_budget):
            attempt += 1
            self.log('redesign', {'stage': stage, 'attempt': attempt,
                                  'failure_modes': reviews[selected].get('failure_modes')})
            notes = {'attempt': attempt, 'failure_modes': reviews[selected].get('failure_modes'),
                     'rollback_stage': reviews[selected].get('rollback_stage'),
                     'view_observations': reviews[selected].get('view_observations'),
                     'rationale': reviews[selected].get('rationale')}
            variants = self.candidate_concepts(task, self.brief, meta, selection, action, candidate_count,
                                               revision_notes=notes, attempt=attempt)
            built = []
            for index, concept in enumerate(variants):
                candidate_dir = stage_dir / ('%s%d' % (self.STAGE_PREFIX[action], index + 1))
                item = build_candidate(concept, candidate_dir, stage=build_stage, scheme=self.args.scheme,
                                       size=self.args.size, orbit=self.orbit)
                item['concept_data'] = concept
                built.append(item)
            for item in built:
                item['response'] = self.review_response(
                    stage, item, candidate_image_labels(item['render_paths'], reduced=not self.orbit))
            reviews = {item['candidate_id']: item['response'] for item in built}
            selected, selection_rationale = self.select_candidate(stage, reviews)
        # The gate keys single-candidate stages by `None`, so register in the same
        # namespace the review will be validated against.
        gate_candidate = (lambda item: item['candidate_id']) if candidate_count > 1 else (lambda item: None)
        for item in built:
            self.register_candidate(task, item, stage_dir, candidate=gate_candidate(item))
        review = {'stage': stage, 'revision': task['revision'], 'artifact_hashes': w.bindings(task),
                  'reviewer': self.config['model'], 'reviewer_type': 'model',
                  'decision': review_decision(reviews, selected),
                  'rationale': selection_rationale, 'selected': selected if candidate_count > 1 else None,
                  'rollback_stage': normalize_rollback(reviews[selected].get('rollback_stage'), stage),
                  'candidates': [{'id': gate_candidate(item), 'decision': item['response'].get('decision'),
                                  'scores': item['response'].get('scores'),
                                  'view_observations': item['response'].get('view_observations', {}),
                                  'reference_comparison': item['response'].get('reference_comparison', {}),
                                  'failure_modes': item['response'].get('failure_modes', [])} for item in built]}
        if candidate_count == 1:
            review.pop('selected')
        blocked = None
        try:
            w.submit_review(task, review)
        except ValueError as error:
            blocked = 'submit_review: ' + str(error)
            self.log('gate_blocked', {'gate': stage, 'error': blocked})
        if blocked is None and review['decision'] == 'pass':
            try:
                w.advance(task)
            except ValueError as error:
                blocked = 'advance: ' + str(error)
                self.log('gate_blocked', {'gate': stage, 'error': blocked})
        self.log('stage', {'name': stage, 'stage_after': task['stage'], 'selected': selected, 'blocked': blocked})
        return {'action': stage, 'stage': task['stage'], 'reviewed_stage': reviewed_stage,
                'selected': selected, 'gate_blocked': blocked,
                'per_candidate_decision': {cid: out.get('decision') for cid, out in reviews.items()},
                'state_lab_plots': next((item.get('state_plots') for item in built if item.get('state_plots')), None),
                'calls': self.client.calls, 'tokens': self.client.tokens}

    def pipeline(self, task):
        """Run the requested stage, then auto-continue only while the stage advances.

        `--action all` is the only mode that continues. A stage whose own selected
        candidate was rejected keeps `task['stage']`, and continuing there would
        rebuild the same stage forever, so the run stops and records the block.
        """
        requested = self.args.action
        auto = requested == 'all'
        summaries = []
        for _ in range(len(w.STAGES) + 1):
            before = task['stage']
            action = self.action_for(task, requested)
            summary = self.stage_pipeline(task, action)
            summaries.append(summary)
            after = task['stage']
            # Compare against the stage the gate was actually reviewed at: running
            # a requested action from research first advances through research and
            # retrieval, and that prefix advance must not be mistaken for the
            # requested stage's own advance.
            reviewed_at = summary.get('reviewed_stage', before)
            self.log('pipeline_iteration', {'action': action, 'requested_stage': before, 'reviewed_at': reviewed_at,
                                            'after': after, 'gate_blocked': summary['gate_blocked'], 'auto': auto})
            if not auto or summary['gate_blocked'] or after == reviewed_at:
                break
            if after in ('game', 'accepted'):
                break
        last = summaries[-1]
        return {'actions': summaries, 'stage': task['stage'], 'gate_blocked': last['gate_blocked'],
                'selected': last['selected'], 'calls': self.client.calls, 'tokens': self.client.tokens}

    def candidate_concepts(self, task, brief, payload, selection, action, count,
                           revision_notes=None, attempt=1):
        """One design call per candidate; a single-candidate stage still varies seeds."""
        concepts = []
        for index in range(count):
            concepts.append(self.draft_concept(task, brief, payload, selection, index=index, stage=action,
                                               total=count, revision_notes=revision_notes, attempt=attempt))
        return concepts

    def frameworks(self, task):
        """Backwards-compatible entry used by the recorded v0.1/v0.2 runs."""
        self.brief = task['brief']
        return self.stage_pipeline(task, 'frameworks')

    def reference_paths(self):
        return sorted((ROOT.parent / '参考图').glob('标准*.png')) + [ROOT.parent / '参考图' / '窗对照总览_街面.png']

    def reference_labels(self):
        return {p.name: 'standard reference' for p in self.reference_paths() if p.exists()}

    def draft_concept(self, task, brief, payload, selection, index=0, stage='frameworks', total=None, scheme=0,
                      revision_notes=None, attempt=1):
        label = '%s_draft_%d' % (stage, index + 1)
        if attempt > 1:
            label += '_retry%d' % attempt
        stage_dir = self.run_dir / stage
        stage_dir.mkdir(parents=True, exist_ok=True)
        # A crashed or interrupted run is resumed by re-running the same command;
        # a concept the model already produced and the contract already accepted
        # must be reused instead of paying for a second design call.
        resolved_path = stage_dir / (label + '.resolved.json')
        if resolved_path.is_file():
            cached = json.loads(resolved_path.read_text(encoding="utf-8"))
            try:
                validate_concept(cached)
            except ValueError as error:
                self.log('draft_cache_rejected', {'label': label, 'reason': str(error)})
            else:
                self.log('draft_cache_hit', {'label': label, 'massing_seed': cached.get('massing_seed')})
                return cached
        if revision_notes is None and self.args.revision_notes:
            revision_notes = json.loads((self.run_dir / self.args.revision_notes).read_text(encoding="utf-8"))
        prompt = design_instruction(brief, payload, revision_notes, stage)
        count = total if total is not None else self.args.candidates
        if count > 1:
            prompt += f'\nThis is candidate {index+1} of {count}; vary at least three massing axes from the others.'
        out = self.call(prompt, max_tokens=4000, label=label)
        (stage_dir / (label + '.json')).write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding="utf-8")
        concept = self.validated_concept(out, brief, payload, selection, prompt, label)
        resolved_path.write_text(json.dumps(concept, ensure_ascii=False, indent=2) + '\n', encoding="utf-8")
        self.log('draft', {'stage': stage, 'index': index + 1, 'attempt': attempt,
                           'massing_seed': concept.get('massing_seed'),
                           'footprint_type': concept.get('footprint_type'), 'storeys': concept.get('storeys'),
                           'evidence_refs': out.get('evidence_refs')})
        return concept

    def allowed_families(self, selection):
        """Families this concept may use: placeable production families only."""
        families = sorted({family for role in (selection or {}).values()
                           if isinstance(role, dict) for family in role})
        return families or sorted(FAMILIES)

    def validated_concept(self, out, brief, payload, selection, prompt, label, repairs=2):
        """Accept a model concept only if it passes the design contract.

        Models routinely invent a plausible family name ("window") that is a study
        family, not a placeable one. One repair is not always enough, and the loop
        is bounded: if the contract still fails, the run stops with a recorded
        error instead of an unhandled traceback.
        """
        concept = out.get('concept', {})
        concept.setdefault('style_id', 'paris_haussmann_v0.1')
        concept['component_policy'] = out.get('component_policy', selection)
        allowed = self.allowed_families(selection)
        last_error = None
        for attempt in range(repairs + 1):
            try:
                validate_concept(concept)
                if attempt:
                    self.log('repair', {'label': label, 'attempt': attempt, 'resolved_error': last_error})
                return concept
            except ValueError as error:
                last_error = str(error)
                self.log('contract_failure', {'label': label, 'attempt': attempt, 'error': last_error})
                if attempt == repairs:
                    break
                repair = (prompt
                          + '\nYour previous JSON failed design-contract validation: ' + last_error
                          + '\nAllowed component_policy families (placeable=true) are exactly: '
                          + ', '.join(allowed)
                          + '\nKeep the massing values, replace every invalid family with one from that list, and '
                            'return ONLY the corrected JSON object.')
                fixed = self.call(repair, max_tokens=4000, label='%s_repair%d' % (label, attempt + 1))
                concept = fixed.get('concept', {})
                concept.setdefault('style_id', 'paris_haussmann_v0.1')
                concept['component_policy'] = fixed.get('component_policy', selection)
        raise ProviderError('Concept failed the design contract after %d repairs: %s' % (repairs, last_error))

    def pilot(self, task):
        """One design -> render -> look -> fix loop, bounded by --revisions."""
        if task['stage'] != 'frameworks':
            self.research(task)
            selection = self.retrieval_stage(task)
        else:
            selection = json.loads((self.run_dir / 'component_selection.json').read_text(encoding="utf-8"))
        payload = json.loads((self.run_dir / 'retrieval_results.json').read_text( encoding="utf-8"))
        brief = task['brief']
        references = sorted((ROOT.parent / '参考图').glob('标准*.png')) + [ROOT.parent / '参考图' / '窗对照总览_街面.png']
        reference_labels = {p.name: 'standard reference' for p in references if p.exists()}
        concept = self.draft_concept(task, brief, payload, selection, index=0)
        history = []
        for revision in range(self.args.revisions + 1):
            candidate_dir = self.run_dir / 'pilot' / f'r{revision}'
            built = build_candidate(concept, candidate_dir, stage=1, scheme=0, size=self.args.size)
            images = candidate_images(built) + [p for p in references if p.exists()]
            out = self.call(look_instruction(brief, built['candidate_id'], candidate_image_labels(built['render_paths']), reference_labels, 'facades'),
                            images=images, max_tokens=6000, label=f'look_r{revision}')
            (candidate_dir / 'look.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding="utf-8")
            self.log('look', {'revision': revision, 'decision': out.get('decision'),
                              'failure_modes': out.get('failure_modes'), 'rollback_stage': out.get('rollback_stage')})
            history.append({'revision': revision, 'schematic': built['schematic'],
                            'decision': out.get('decision'), 'failure_modes': out.get('failure_modes'),
                            'rollback_stage': out.get('rollback_stage'),
                            'observed_views': len(out.get('view_observations', {}))})
            if out.get('decision') == 'pass' or revision == self.args.revisions:
                break
            notes = {'failure_modes': out.get('failure_modes'), 'rollback_stage': out.get('rollback_stage'),
                     'view_observations': out.get('view_observations'), 'rationale': out.get('rationale')}
            prompt = design_instruction(brief, payload, notes)
            fixed = self.call(prompt, max_tokens=4000, label=f'fix_r{revision+1}')
            concept = self.validated_concept(fixed, brief, payload, selection, prompt, f'fix_r{revision+1}')
            self.log('fix', {'revision': revision + 1, 'massing_seed': concept.get('massing_seed'),
                             'footprint_type': concept.get('footprint_type')})
        return {'action': 'pilot', 'stage': task['stage'], 'history': history,
                'calls': self.client.calls, 'tokens': self.client.tokens}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', required=True)
    p.add_argument('--action', choices=['pilot', 'frameworks', 'facades', 'tier2', 'tier3', 'delivery', 'all'],
                   default='pilot')
    p.add_argument('--provider', default='configs/providers/deepseek.json')
    p.add_argument('--brief')
    p.add_argument('--candidates', type=int, default=1)
    p.add_argument('--scheme', type=int, default=1)
    p.add_argument('--attempts', type=int, default=1,
                   help='bounded re-design attempts per stage; a rejection feeds its failure modes back into the next attempt')
    p.add_argument('--views', choices=['full', 'reduced'], default='full',
                   help='full = 7 fixed + 16 orbit views; reduced = 7 fixed only (recorded as a reduced review)')
    p.add_argument('--revisions', type=int, default=1)
    p.add_argument('--size', type=int, default=560)
    p.add_argument('--revision-notes')
    a = p.parse_args()
    try:
        Runner(a).run()
    except ProviderError as error:
        print('PROVIDER_ERROR: ' + str(error), file=sys.stderr)
        raise SystemExit(2)


if __name__ == '__main__':
    main()
