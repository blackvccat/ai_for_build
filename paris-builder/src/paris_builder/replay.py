"""Deterministic offline replay client for the design pipeline.

Purpose: exercise the whole evidence-gated chain (research -> retrieval ->
frameworks -> facades -> tier2 -> tier3 -> delivery) without a network call, so
the stage wiring, artifact registration, view mapping, state lab and gate
validation are all covered by tests. It is a TEST FIXTURE: `runs/` produced with
it must be reported as offline replay, never as live model evidence.

The scripted critic judges only massing that the renderer can actually show: a
candidate with fewer than five storeys is rejected with a stored rollback target,
everything else passes. That keeps both the blocked-gate path and the advance
path reachable and reproducible.
"""
from __future__ import annotations

import json
import re

from . import workflow as w
from .components import FAMILIES

CANDIDATE = re.compile(r'([a-z]{2}\d+)')
CANDIDATES_BLOCK = re.compile(r'CANDIDATES:\s*(\{.*\})\s*$', re.DOTALL)
# 6317 is the deliberately short massing the fixture critic rejects, placed first
# so the blocked-gate path is reproducible; the rest also differ in footprint,
# width, depth and seeds so the frameworks diversity gate passes.
DRAFT_SEEDS = (6317, 6421, 6521, 6101, 6211)
FOOTPRINTS = ('enclosed_court', 'l_plan', 'enclosed_court', 'open_court', 'l_plan')
# Deterministic scripted verdict per seed: 6317 is the deliberately short massing
# that the fixture critic rejects, so the blocked-gate path stays reproducible.
STOREYS_BY_SEED = {6101: 5, 6211: 6, 6317: 4, 6421: 5, 6521: 6}


def _candidate_ids(prompt):
    """Candidate ids offered by a selection prompt, in order.

    The selection prompt embeds the candidates as JSON under `CANDIDATES:`, so
    parse that object instead of guessing at an id pattern; a wrong guess would
    silently make the fixture "select" a candidate that was never reviewed.
    """
    block = CANDIDATES_BLOCK.search(prompt)
    if block:
        try:
            loaded = json.loads(block.group(1))
            if isinstance(loaded, dict):
                return list(loaded)
        except ValueError:
            pass
    order = []
    for match in CANDIDATE.finditer(prompt):
        if match.group(1) not in order:
            order.append(match.group(1))
    return order


class ReplayClient:
    """Same call surface as MultimodalClient, but scripted and offline."""

    def __init__(self, config, jobs=None):
        self.config = config
        self.calls = 0
        self.tokens = 0
        self.usage = []
        self.jobs = jobs or {}
        self.label = 'replay-fixture'
        # force_pass drives the pipeline's advance path in tests. It is a fixture
        # switch, not a judgement: `verdict` stays recorded per candidate.
        self.force_pass = bool(config.get('force_pass'))
        # Concepts are counted separately from total calls so the first candidate
        # is always the same seed regardless of how many research/retrieval calls
        # happened earlier in the run.
        self.designs = 0
        self.looks = 0

    # --- scripted payloads -------------------------------------------------
    def _concept(self):
        index = self.designs % len(DRAFT_SEEDS)
        self.designs += 1
        seed = DRAFT_SEEDS[index]
        storeys = STOREYS_BY_SEED[seed]
        width = 69 + index * 3
        court_width = 25 - index
        return {
            'concept': {'width': width, 'depth': 43 + index, 'chamfer': 10 - index, 'court_width': court_width,
                        'court_depth': 25, 'storeys': storeys, 'bay_pitch': 6, 'roof_height': 11,
                        'entrance_fraction': 0.38, 'footprint_type': FOOTPRINTS[index],
                        'roof_profile': 'steep_lower_shallow_crown', 'massing_seed': seed,
                        'facade_seed': 4409 + index, 'detail_seed': 5519 + index},
            'component_policy': {role: {'shopfront' if role in ('primary_street', 'corner') else 'window_surround':
                                        {'variant': 0, 'reason': 'fixture policy for offline replay',
                                         'evidence_refs': ['fixture']}}
                                 for role in ('primary_street', 'secondary_street', 'corner', 'rear_return',
                                              'service_street', 'courtyard')},
            'rationale': 'Offline replay fixture. Not design evidence.',
            'evidence_refs': ['fixture'],
        }

    def _look(self, prompt):
        # The review prompt names the candidate id, not its seeds, so the fixture
        # walks its own design order: candidates are built and reviewed in the
        # same sequence the concepts were emitted.
        seed = DRAFT_SEEDS[self.looks % len(DRAFT_SEEDS)]
        self.looks += 1
        scripted = STOREYS_BY_SEED.get(seed, 6) >= 5
        decision = 'pass' if (scripted or self.force_pass) else 'reject'
        return {
            'decision': decision,
            'scores': [17, 17, 17, 17, 17],
            'view_observations': {view: 'offline replay observation for ' + view for view in w.VIEWS},
            'reference_comparison': {'standard_%d' % i: 'offline replay comparison' for i in range(5)},
            'failure_modes': ['none' if decision == 'pass' else 'massing too short for the reviewed silhouette'],
            'rollback_stage': 'frameworks',
            'rationale': 'Offline replay fixture decision; no claim about real quality.',
        }

    def _select(self, prompt):
        ids = _candidate_ids(prompt)
        return {'selected': ids[0] if ids else 'mf1', 'rationale': 'offline replay fixture selection'}

    def _research(self):
        return {'research_evidence': {'sources': [{'url': 'https://example.org/%d' % i,
                                                  'observations': ['offline replay fixture observation']}
                                                 for i in range(3)],
                                      'design_inferences': ['offline replay fixture inference'],
                                      'boundaries': ['offline replay fixture boundary']},
                'rationale': 'Offline replay fixture research. Not live research.'}

    def _retrieval(self, prompt):
        families = sorted(FAMILIES)
        policy = {role: {families[0]: {'variant': 0, 'reason': 'offline replay fixture',
                                       'evidence_refs': ['fixture']}} for role in
                  ('primary_street', 'secondary_street', 'corner', 'rear_return', 'service_street', 'courtyard')}
        return {'component_selection': policy, 'rejected': [], 'rationale': 'Offline replay fixture selection.'}

    # --- call surface ------------------------------------------------------
    def complete(self, prompt, images=(), max_tokens=3500):
        self.calls += 1
        self.tokens += 0
        if 'research_evidence' in prompt:
            result = self._research()
        elif 'component_selection' in prompt and 'CANDIDATES:' in prompt:
            result = self._retrieval(prompt)
        elif 'Select ONE' in prompt:
            result = self._select(prompt)
        elif 'STAGE SCOPE' in prompt:
            result = self._look(prompt)
        else:
            result = self._concept()
        receipt = {'model': self.label, 'usage': {'total_tokens': 0}, 'elapsed_seconds': 0.0,
                   'prompt_sha256': '', 'image_evidence': [], 'request_id': 'replay-%d' % self.calls,
                   'call': self.calls, 'offline_replay': True}
        self.usage.append(receipt)
        return result, receipt


def load_client(config):
    """Entry point used by tools/model_design_run.py for the replay provider."""
    return ReplayClient(config)
