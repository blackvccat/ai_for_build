"""Hash-bound candidate memory. Retention never changes a review's decision.

The index is a projection over immutable snapshots. A restored design receives a
new revision and new evidence bindings; every stage still needs a fresh review.
Historical model checks are an explicitly separate, provisional search metric.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import shutil
import threading
import uuid

from .operations import timestamp, write_json
from . import workflow as w

LOCK = threading.RLock()
DESIGN_STAGES = ('frameworks', 'facades', 'tier2', 'tier3')


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _identity(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _folder(task):
    return Path(task['path']).resolve().parent / 'candidate-search'


def _index(task):
    path = _folder(task) / 'index.json'
    return _read(path) if path.exists() else {'version': 1, 'candidates': {}, 'best': {}}


def _score(row):
    values = row.get('scores', [])
    if (not isinstance(values, list) or len(values) != 5 or any(type(v) not in (int, float) or not math.isfinite(v)
                               or not 0 <= v <= 20 for v in values)):
        return 0
    return sum(values)


def _historical_checks(row, task, stage):
    actual = {}
    for field in ('geometry_checks', 'layer_checks'):
        actual.update({field + '/' + k: v for k, v in row.get(field, {}).items()})
    for field in ('detail_checks', 'storey_checks'):
        for group, checks in row.get(field, {}).items():
            actual.update({field + '/' + group + '/' + k: v for k, v in checks.items()})
    expected = {'layer_checks/' + k for k in w.LAYER_CHECKS}
    if stage == 'frameworks':
        expected.update('geometry_checks/' + k for k in w.GEOMETRY_CHECKS)
    else:
        expected.update('detail_checks/' + g + '/' + k for g in w.LAYER_CHECKS[:5]
                        for k in w.DETAIL_CHECKS)
        expected.update('storey_checks/' + str(i) + '/' + k
                        for i in range(task.get('intent', {}).get('storeys', 0)) for k in w.DETAIL_CHECKS)
    statuses = {}
    for key in expected:
        item = actual.get(key)
        statuses[key] = (item.get('status') if isinstance(item, dict) and
                         isinstance(item.get('observation'), str) and item['observation'].strip()
                         else 'unsupported')
    failed = sum(s == 'fail' for s in statuses.values())
    na = sum(s == 'not_applicable' for s in statuses.values())
    unresolved = sum(s not in ('pass', 'fail', 'not_applicable') for s in statuses.values())
    return {'mode': 'historical-v1', 'feasible': None, 'failed': failed,
            'unsupported': unresolved, 'unverified_applicability': na,
            'passed': sum(s == 'pass' for s in statuses.values()),
            'required_ids': sorted(expected), 'passed_ids': [],
            'quality_total': _score(row),
            'rank': [failed + unresolved + na, unresolved + na, failed, -_score(row)],
            'limitations': ['Historical visual checks are not deterministic conformance.',
                           'Historical N/A applicability has not been independently verified.']}


def _metric(row, task, stage, conformance, schematic, plan):
    if conformance is None:
        return _historical_checks(row, task, stage)
    if (conformance.get('source', {}).get('sha256') != _digest(schematic)
            or conformance.get('stage') != stage):
        raise ValueError('Candidate conformance is bound to a different export or stage')
    normalized = {k: v for k, v in plan.items() if k != '_stage'}
    # The conformance adapter owns plan hashing; require its binding when supplied.
    if conformance.get('plan_sha256') != _identity(normalized):
        raise ValueError('Candidate conformance is bound to a different plan')
    checks = conformance.get('checks')
    if not isinstance(checks, list) or not checks or any(not isinstance(c, dict) or
            not c.get('id') or type(c.get('required')) is not bool or
            c.get('status') not in ('pass', 'fail', 'unsupported') for c in checks):
        raise ValueError('Candidate conformance needs explicit checks and applicability')
    if len({c['id'] for c in checks}) != len(checks):
        raise ValueError('Candidate conformance repeats a check identity')
    required = [c for c in checks if c['required']]
    if not required:
        raise ValueError('Candidate conformance has no required checks')
    failed = sum(c['status'] == 'fail' for c in required)
    unresolved = sum(c['status'] == 'unsupported' for c in required)
    quality = row.get('quality_checks', {})
    quality_statuses = []
    for key in w.QUALITY_CHECKS:
        item = quality.get(key)
        quality_statuses.append(item['status'] if isinstance(item, dict) and
                                item.get('status') in ('pass', 'fail', 'uncertain') and
                                isinstance(item.get('observation'), str) and item['observation'].strip()
                                else 'uncertain')
    quality_failed = quality_statuses.count('fail')
    quality_uncertain = quality_statuses.count('uncertain')
    return {'mode': 'conformance-v1', 'policy_id': conformance.get('policy_id'),
            'validator_sha256': conformance.get('validator_sha256'),
            'feasible': not (failed or unresolved), 'failed': failed, 'unsupported': unresolved,
            'passed': sum(c['status'] == 'pass' for c in required),
            'required_ids': sorted(c['id'] for c in required),
            'passed_ids': sorted(c['id'] for c in required if c['status'] == 'pass'),
            'quality_failed': quality_failed, 'quality_uncertain': quality_uncertain,
            'quality_total': _score(row),
            'rank': [int(bool(failed or unresolved)), failed + unresolved, unresolved,
                     failed, quality_failed + quality_uncertain, quality_uncertain,
                     quality_failed], 'limitations': []}


def _binding_info(task, path, revision, candidate):
    existing = next((a for a in task.get('artifacts', []) if Path(a['path']).resolve() == path), None)
    if existing:
        return {k: existing[k] for k in ('kind', 'stage', 'revision', 'candidate', 'view_set') if k in existing}
    parts = path.parts
    stage = next((s for s in DESIGN_STAGES if s in parts), None)
    if stage:
        pos = parts.index(stage)
        ident = parts[pos + 1] if pos + 1 < len(parts) else candidate
        ident = None if ident == 'selected' else ident.split('-attempt-')[0]
    else:
        stage, ident = ('retrieval' if 'retrieval' in parts else 'research'), None
    kinds = {'candidate.schem': 'schematic', 'concept.json': 'concept',
             'assembly_plan.json': 'assembly_plan', 'views.json': 'views'}
    kind = kinds.get(path.name, path.stem)
    for measured_kind in ('facade_section', 'architectural_evidence', 'architectural_conformance'):
        if path.stem.startswith(measured_kind + '-v'):
            kind = measured_kind
    return {'kind': kind, 'stage': stage,
            'revision': revision, 'candidate': ident,
            **({'view_set': 'reduced'} if path.name == 'views.json' and stage == 'frameworks' else {})}


def _snapshot(task, review, row, conformance):
    run = Path(task['path']).resolve().parent
    stage, revision, ident = review['stage'], review['revision'], row.get('id')
    bindings = review.get('artifact_hashes')
    if not isinstance(bindings, dict) or not bindings:
        raise ValueError('Candidate review has no artifact hash bindings')
    receipts, paths = [], {}
    def include(path, expected=None, info=None, registered=False):
        path = Path(path).resolve()
        if not path.is_file() or (expected and _digest(path) != expected):
            raise ValueError('Changed or missing candidate evidence: ' + str(path))
        if str(path) in paths:
            return
        # Equal artifacts across revisions share one immutable content blob.
        stored = 'blobs/' + _digest(path)
        receipt = {'original_path': str(path), 'stored_path': stored,
                   'sha256': _digest(path), 'bytes': path.stat().st_size,
                   'registered': registered, **(info or {})}
        paths[str(path)] = receipt
        receipts.append(receipt)
        if info and info.get('kind') == 'views':
            for view in _read(path).values():
                include(view['path'], view['sha256'])
    for source, expected in bindings.items():
        path = Path(source).resolve()
        include(path, expected, _binding_info(task, path, revision, ident), True)
    current = [r for r in receipts if r.get('stage') == stage and r.get('candidate') == ident]
    schematic = next((r for r in current if r.get('kind') == 'schematic'), None)
    plan_receipt = next((r for r in current if r.get('kind') in ('assembly_plan', 'concept')), None)
    technical = next((r for r in current if r.get('kind') == 'technical_validation'), None)
    if not schematic or not plan_receipt or not technical:
        raise ValueError('Candidate needs bound schematic, plan and technical evidence')
    technical_data = _read(technical['original_path'])
    if technical_data.get('status') != 'PASS':
        raise ValueError('Technically invalid candidate cannot enter retained search')
    plan = _read(plan_receipt['original_path'])
    generator = technical_data.get('generator_version')
    if generator:
        generator_manifest = Path(generator['path']) / 'version.json'
        metadata = _read(generator_manifest)
        content_id = hashlib.sha256(json.dumps(metadata['files'], sort_keys=True).encode()).hexdigest()
        if metadata['id'] != generator['id'] or content_id != generator['id']:
            raise ValueError('Candidate generator identity changed')
        include(generator_manifest)
        generator_files = dict(metadata['files'])
        for name, expected in generator_files.items():
            include(Path(generator['path']) / name, expected)
        generator = {**generator, 'files': generator_files}
    else:
        # No historical source snapshot means reproducibility remains explicitly unknown.
        generator = {'id': None, 'path': None, 'files': {}, 'reproducibility': 'UNVERIFIED'}
    for extra in Path(schematic['original_path']).parent.iterdir():
        if extra.is_file():
            include(extra)
    candidate_id = _identity({'stage': stage, 'schematic': schematic['sha256'],
                             'plan': plan_receipt['sha256'],
                             'generator': {'id': generator['id'], 'files': generator['files']}})
    metric = _metric(row, task, stage, conformance, schematic['original_path'], plan)
    body = {'version': 1, 'candidate_id': candidate_id, 'stage': stage, 'original_revision': revision,
            'label': ident, 'plan': plan, 'generator': generator, 'files': receipts,
            'original_review': deepcopy(review), 'candidate_review': deepcopy(row),
            'metric': metric, 'conformance': deepcopy(conformance),
            'approval': 'RE_REVIEW_REQUIRED', 'game_acceptance': 'PENDING'}
    snapshot_id = _identity(body)
    target = _folder(task) / 'snapshots' / snapshot_id
    body['snapshot_id'] = snapshot_id
    if not target.exists():
        temporary = target.with_name(snapshot_id + '.pending-' + uuid.uuid4().hex)
        temporary.mkdir(parents=True)
        try:
            for receipt in receipts:
                destination = _folder(task) / receipt['stored_path']
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.exists():
                    pending = destination.with_name(destination.name + '.pending-' + uuid.uuid4().hex)
                    try:
                        shutil.copyfile(receipt['original_path'], pending)
                        if _digest(pending) != receipt['sha256']:
                            raise ValueError('Candidate evidence changed while snapshotting')
                        pending.rename(destination)
                    finally:
                        pending.unlink(missing_ok=True)
                if _digest(destination) != receipt['sha256']:
                    raise ValueError('Candidate evidence changed while snapshotting')
            write_json(temporary / 'snapshot.json', body)
            temporary.rename(target)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    verify(task, snapshot_id)
    return body


def verify(task, snapshot_id):
    target = _folder(task) / 'snapshots' / snapshot_id
    body = _read(target / 'snapshot.json')
    if body.get('snapshot_id') != snapshot_id or _identity({k: v for k, v in body.items()
                                                         if k != 'snapshot_id'}) != snapshot_id:
        raise ValueError('Retained candidate manifest identity changed')
    for receipt in body['files']:
        source = (_folder(task) / receipt['stored_path']).resolve()
        if (receipt['stored_path'] != 'blobs/' + receipt['sha256'] or
                not source.is_relative_to(_folder(task).resolve()) or not source.is_file() or
                _digest(source) != receipt['sha256']):
            raise ValueError('Retained candidate evidence changed: ' + receipt['stored_path'])
    return body


def _promotion(candidate, incumbent):
    metric, old = candidate['metric'], incumbent['metric']
    if metric['mode'] != old['mode']:
        return False, ['different_evidence_policy']
    if (metric['required_ids'] != old['required_ids'] or metric.get('policy_id') != old.get('policy_id')
            or metric.get('validator_sha256') != old.get('validator_sha256')):
        return False, ['different_conformance_obligations']
    regressions = sorted(set(old['passed_ids']) - set(metric['passed_ids']))
    if regressions:
        return False, regressions
    return metric['rank'] < old['rank'], []


def retain_review(task, review, *, conformance_by_candidate=None):
    """Persist reviewed candidates and the incumbent; never mutate or save task."""
    if review.get('stage') not in DESIGN_STAGES:
        return summary(task)
    with LOCK:
        index = _index(task)
        for row in review.get('candidates', []):
            conformance = (conformance_by_candidate or {}).get(row.get('id'))
            body = _snapshot(task, review, row, conformance)
            sid = body['snapshot_id']
            entry = {k: body[k] for k in ('candidate_id', 'snapshot_id', 'stage', 'original_revision',
                                          'label', 'metric', 'approval')}
            entry['original_decision'] = row.get('decision')
            index['candidates'][sid] = entry
            key = body['stage'] + ':' + body['metric']['mode']
            previous = index['best'].get(key)
            promote, regressions = (True, []) if previous is None else _promotion(entry, index['candidates'][previous])
            if promote:
                index['best'][key] = sid
            entry['regressions'] = regressions
        index['updated_at'] = timestamp()
        write_json(_folder(task) / 'index.json', index)
        return summary(task)


def import_history(task, stage='facades', min_revision=None):
    """Backfill original bound reviews. Invalid historical evidence is reported."""
    skipped = []
    for review in task.get('reviews', []):
        if review.get('stage') != stage or (min_revision is not None and review.get('revision', -1) < min_revision):
            continue
        try:
            retain_review(task, review)
        except (ValueError, FileNotFoundError, KeyError) as error:
            skipped.append({'revision': review.get('revision'), 'reason': str(error)})
    return {**summary(task), 'skipped': skipped}


def summary(task):
    index = _index(task)
    return {'version': 1, 'candidates_retained': len(index['candidates']),
            'best': {key: deepcopy(index['candidates'][sid]) for key, sid in index['best'].items()},
            'restoration': deepcopy(task.get('candidate_restoration')),
            'game_acceptance': task.get('game_acceptance', 'PENDING')}


def select_revision(task, source_revision, stage=None):
    """Select retained evidence for an explicitly requested historical revision."""
    choices = [entry for entry in _index(task)['candidates'].values()
               if entry['stage'] == (stage or task['stage']) and entry['original_revision'] == source_revision]
    if not choices:
        raise ValueError('No retained evidence for the requested historical revision')
    choices.sort(key=lambda entry: (entry['metric']['mode'] != 'conformance-v1', entry['metric']['rank']))
    verify(task, choices[0]['snapshot_id'])
    return choices[0]['snapshot_id']


def restore(task, candidate_id=None, *, snapshot_id=None, revision=None, stage=None):
    """Return a NEW task dict after copying retained bytes into a new revision.

    The caller saves this result and independently regenerates current measured
    evidence. Original decisions stay in historical reviews; approvals never move.
    """
    index = _index(task)
    stage = stage or task['stage']
    if stage not in DESIGN_STAGES or task['stage'] == 'accepted':
        raise ValueError('Only active architectural stages support candidate restoration')
    if snapshot_id is None:
        if candidate_id is None:
            snapshot_id = index['best'].get(stage + ':conformance-v1') or index['best'].get(stage + ':historical-v1')
            if snapshot_id is None:
                raise ValueError('No retained incumbent for this stage')
        else:
            choices = [e for e in index['candidates'].values() if e['stage'] == stage and
                       e['candidate_id'] == candidate_id and not e.get('regressions')]
            if not choices:
                raise ValueError('No retained candidate without regressions for the requested design')
            choices.sort(key=lambda e: (e['metric']['mode'] != 'conformance-v1', e['metric']['rank']))
            snapshot_id = choices[0]['snapshot_id']
    body = verify(task, snapshot_id)
    if body['stage'] != stage:
        raise ValueError('Retained candidate belongs to a different stage')
    run = Path(task['path']).resolve().parent
    existing = [int(p.name.removeprefix('revision-')) for p in run.glob('revision-*')
                if p.is_dir() and p.name.removeprefix('revision-').isdigit()]
    new_revision = max([task['revision'], *existing]) + 1 if revision is None else revision
    if new_revision <= task['revision'] or (run / ('revision-' + str(new_revision))).exists():
        raise ValueError('Restoration requires an unused NEW revision')
    target = run / ('revision-' + str(new_revision))
    temporary = target.with_name(target.name + '.restore-' + uuid.uuid4().hex)
    source = _folder(task)
    path_map = {}
    destinations = {}
    for receipt in body['files']:
        original = Path(receipt['original_path'])
        if body['generator']['path'] and original.is_relative_to(Path(body['generator']['path'])):
            relative = Path('generator') / body['generator']['id'] / original.name
        elif original.is_relative_to(run):
            relative = original.relative_to(run)
            if relative.parts[0].startswith('revision-'):
                relative = Path(*relative.parts[1:])
            else:
                relative = Path('inputs') / relative
        else:
            relative = Path('inputs') / _identity(str(original))[:16] / original.name
        destination = target / relative
        if str(destination) in destinations and destinations[str(destination)] != receipt['sha256']:
            raise ValueError('Restored candidate paths collide')
        destinations[str(destination)] = receipt['sha256']
        path_map[str(original)] = str(destination)
    def rebase(value):
        if isinstance(value, dict):
            return {path_map.get(k, k): rebase(v) for k, v in value.items()}
        if isinstance(value, list):
            return [rebase(v) for v in value]
        if isinstance(value, str):
            if value in path_map:
                return path_map[value]
            if body['generator']['path'] and value == body['generator']['path']:
                return str(target / 'generator' / body['generator']['id'])
        return value
    try:
        for receipt in body['files']:
            destination = temporary / Path(path_map[receipt['original_path']]).relative_to(target)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / receipt['stored_path'], destination)
            if destination.suffix == '.json':
                data = _read(destination)
                rebased = rebase(data)
                if rebased != data:
                    write_json(destination, rebased)
        # All registered receipts receive hashes of the actual restored evidence.
        artifacts = []
        for receipt in body['files']:
            # Fresh conformance must be measured under the current policy. Historical
            # reports remain copied provenance but are never active restored evidence.
            if not receipt['registered'] or receipt.get('kind') == 'architectural_conformance':
                continue
            artifact = {k: receipt[k] for k in ('kind', 'stage', 'candidate', 'view_set') if k in receipt}
            path = Path(path_map[receipt['original_path']])
            artifact.update(path=str(path), revision=new_revision,
                            sha256=_digest(temporary / path.relative_to(target)))
            artifacts.append(artifact)
        temporary.rename(target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    result = deepcopy(task)
    result.update(stage=stage, revision=new_revision, artifacts=artifacts,
                  awaiting='VISUAL_REVIEW', game_acceptance='PENDING')
    result['selected'] = {}
    for artifact in artifacts:
        if artifact['stage'] == 'frameworks' and artifact['kind'] == 'concept' and stage != 'frameworks':
            result['selected']['frameworks'] = {'candidate': artifact['candidate'], 'plan': _read(artifact['path'])}
    if body['generator']['id']:
        result['generator_version'] = {'id': body['generator']['id'],
                                       'path': str(target / 'generator' / body['generator']['id'])}
    else:
        result.pop('generator_version', None)
    result['candidate_restoration'] = {'candidate_id': body['candidate_id'], 'snapshot_id': snapshot_id,
                                      'source_revision': body['original_revision'], 'revision': new_revision,
                                      'original_decision': body['candidate_review'].get('decision'),
                                      'approval': 'RE_REVIEW_REQUIRED', 'restored_at': timestamp()}
    result.setdefault('history', []).append({'candidate_restore': result['candidate_restoration']})
    return result
