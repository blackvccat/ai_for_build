"""Website production workflow with bound evidence and user-only final acceptance."""
import json
from pathlib import Path
import shutil
import subprocess
import zipfile
import time

import numpy as np

from . import design, workflow as w
from .operations import ROOT, Operation, write_json, file_receipt
from .learning import KnowledgeIndex, digest, read_json
from .exporter import write_schematic
from .schematic import load_schematic
from .geometry import inspect_geometry
from .facade_section import measure as measure_facade_section
from .facade_section import review_evidence as section_review_evidence
from .fonts import node_binary
from .preview3d import render_previews
from .executor import view_bundle, fixed_view_bundle, state_lab
from .cancellation import checkpoint

STAGES = ('frameworks', 'facades', 'tier2', 'tier3', 'delivery')


def load(folder):
    return w.load(Path(folder) / 'workflow.json')


def record(task, folder, kind, value, candidate=None, view_set=None):
    path = Path(folder) / (kind + '.json')
    write_json(path, value)
    w.register_artifact(task, kind, path, candidate, view_set=view_set)
    return path


def measured_advance(task, rationale):
    review = {'stage': task['stage'], 'revision': task['revision'], 'artifact_hashes': w.bindings(task),
              'reviewer': 'site-evidence-validator', 'reviewer_type': 'software',
              'decision': 'pass', 'rationale': rationale}
    w.submit_review(task, review)
    w.advance(task)


def create(folder, intent, inference, selections):
    folder = Path(folder)
    operation = Operation('workflow.initialize', intent, evidence=inference['evidence_ids'])
    try:
        language = inference.get('architectural_contract') or {
            'style': 'Paris Haussmann', 'invariants': inference.get('research_evidence', {}).get('design_inferences', []),
            'variation_axes': ['massing', 'opening_rhythm', 'floor_hierarchy', 'roof_section', 'material_relationships'],
            'relationships': inference.get('facade_decisions', []),
            'uncertainties': inference.get('research_evidence', {}).get('boundaries', [])}
        if not isinstance(language, dict) or not isinstance(language.get('style'), str):
            raise ValueError('设计源语需要明确建筑类型/风格及规制')
        brief = {'style': language['style'], 'design_language': language, 'use': intent['request'],
                 'scale_budget': {k: intent[k] for k in ('width', 'depth', 'storeys')},
                 'views': list(w.VIEWS), 'minecraft_version': '1.21.11', 'data_version': 4671,
                 'plot': '按结构形式区分临街、后院与邻接山墙；未知现场条件列为待确认',
                 'prohibitions': ['no invented visual acceptance', 'no source mutation',
                                  'no detail before framework review'],
                 'candidate_scale_policy': 'Requested width, depth and storeys stay fixed; vary bay pitch, entrance and roof profile.'}
        task = w.create_task(folder / 'workflow.json', brief, 'deepseek-flash / DSH',
                             {'image_input': True, 'visual_reviewer': 'agent',
                              'model_image_input': True})
        task['score_profile'] = 'strict'
        task['review_policy'] = 'layered-v2'
        task['production_adapter'] = 'house-three-layer-v1'
        task['execution_evidence'] = 'LIVE_DSH' if inference.get('runtime_receipts') else 'LOCAL_EVIDENCE_ONLY'
        task['intent'] = intent
        task['execution_mode'] = 'autonomous'
        task['pending_capability_gaps'] = inference.get('unsupported_decisions', [])
        task['selected'] = {}
        w.save(task)
        base = folder / 'evidence'
        style = inference.get('style_model') or ({'style_id': language['style'], 'invariants': language.get('invariants', []),
            'relationships': language.get('relationships', []), 'variation_axes': language.get('variation_axes', []),
            'evidence': inference['research_evidence']} if language['style'] != 'Paris Haussmann' else
            read_json(ROOT / 'knowledge/styles/paris_haussmann_v0.1.json'))
        record(task, base, 'style_model', style)
        record(task, base, 'research_evidence', inference['research_evidence'])
        measured_advance(task, 'Three distinct source URLs have observations; inferences and boundaries are recorded. This checks evidence structure, not source completeness.')
        record(task, base, 'retrieval_results', selections)
        candidates = {row['id']: row for rows in selections.values() for row in rows}
        selected = inference['evidence_ids']
        if not selected or any(ident not in candidates for ident in selected):
            raise ValueError('Selected evidence was not retrieved')
        if {candidates[ident]['layer'] for ident in selected} != {'structure', 'facade', 'technique', 'component'}:
            raise ValueError('Formal planning must cite structure, facade, technique and component evidence')
        record(task, base, 'component_selection', {
            'selected': [{'id': ident, 'record': candidates[ident], 'role': 'design_reference',
                          'reason': 'DSH cited this evidence; compatibility still requires candidate review'} for ident in selected],
            'not_selected': [{'id': ident, 'reason': 'Retrieved alternative not selected by this plan'}
                             for ident in candidates if ident not in selected],
            'scope': 'Reference selection does not imply placement of an automatic crop',
            'decisions': inference['facade_decisions']})
        measured_advance(task, 'Actual four-layer retrieval and all selected/unselected IDs preserved; reference use distinguished from physical placement.')
        operation.finish(w.status(task), artifacts=[folder / 'workflow.json'], validation={'research': 'PASS', 'retrieval': 'PASS'})
        return task
    except Exception as error:
        operation.fail(str(error))
        raise


def plans(task):
    intent = task['intent']
    base = {k: intent[k] for k in ('form', 'scheme', 'width', 'depth', 'storeys', 'seed')}
    if intent.get('detail_profile'): base['detail_profile'] = intent['detail_profile']
    stage = task['stage']
    if stage == 'frameworks':
        # ONE framework, and it must reach the gate. The brief is fixed, so a five-way
        # comparison only multiplied build/render/review cost by five and made it easy to
        # ship the least-bad candidate; anything short of the gate gets repaired instead.
        rows = task.get('framework_proposals') or [{'parameters': {}}]
        return [('frame-1', {**base, **rows[0].get('parameters', {})})]
    framework = task['selected']['frameworks']['plan']
    if stage == 'facades':
        # ONE elevation, held to the same standard as the framework. Comparing three
        # schemes multiplied build/render/review cost by three for a composition the brief
        # already fixes; a scheme that falls short gets repaired, not swapped.
        return [('facade-1', {**framework, 'scheme': intent['scheme'] or 'haussmann_apartment'})]
    return [(None, task['selected']['facades']['plan'])]


def prepare_framework_contract(task, folder, key, model, emit=None):
    from .harness_runtime import run_json
    from .generator_repair import sources
    from .technique_library import brief as technique_brief
    session = task['intent'].get('session')
    if not session or task.get('framework_policy') == 'prompt-bound-v1':
        return
    history = read_json(ROOT / 'runs/LEARNING-WORKBENCH-v1/agent-sessions' / (session + '.json'))
    messages = [{'role': 'user' if event['kind'] == 'user' else 'assistant',
                 'content': event.get('text') or event.get('summary', '')}
                for event in history['events'] if event['kind'] in ('user', 'assistant', 'plan')]
    # The operator's reference photos ARE analysed for the conversation, but that analysis
    # never reached framework planning: `conversation` drops it (its kind is
    # 'reference_analysis', not one of the three kept kinds) and the payload had no field
    # for it either. So the geometry was decided without the evidence the operator
    # actually supplied. Carry the latest analysis into the planning payload.
    analyses = [event for event in history['events'] if event.get('kind') == 'reference_analysis']
    reference = None
    if analyses:
        latest = analyses[-1]
        reference = {'observations': latest.get('observations'),
                     'references': [{'name': row.get('name'), 'note': row.get('note')}
                                    for row in (latest.get('references') or [])]}
    snapshot = Path(folder) / 'framework-contract-source'
    snapshot.mkdir(exist_ok=True)
    source_text = sources(task)
    for name, text in source_text.items():
        (snapshot / name).write_text(text, encoding='utf-8', newline='\n')
    payload = {'conversation': messages, 'brief': task['brief'], 'intent': task['intent'],
               'reference_analysis': reference,
               'technique_catalogue': technique_brief(),
               # 先造型、后细节：把两层的边界写进规划上下文，而不是留在构建器的隐式分支里。
               'layer_contract': {
                   'massing_tier0': '体量、屋顶形制（三段芒萨尔：陡下坡—坡折—缓上坡—屋脊）、转角切角与檐口交圈、'
                                    '开间节奏与洞口、入口轴、阳台大线',
                   'detail_tier123': '窗套/窗台/窗楣、竖梃与横梃、层间带、店面与招牌带、栏杆、锈石、转角石、'
                                     '老虎窗、立面与屋顶交接',
                   'order': '造型未成立不得堆细节；细节问题不得倒逼造型，除非结构形制本身不成立',
               },
        'instruction': 'First inspect the actual active generator using generator_source_map and read_generator_source. '
        'Reconstruct the complete user-confirmed building brief from the conversation. '
        'Later corrections amend it; they do not replace earlier confirmed requirements. Assistant suggestions '
        'are binding only when the user accepted them. Distinguish camera perspective from actual oblique or '
        'chamfered building geometry. Return JSON confirmed_brief (full Chinese specification), '
        'architectural_contract {style,invariants,variation_axes,relationships,uncertainties}, '
        'unsupported_decisions (explicit requested geometry missing in the current adapter), '
        'framework_candidate (ONE object: parameters and rationale). The operator requires '
        'a single design that meets the standard, not a set of variants to choose between. '
        'Every candidate must satisfy the same confirmed constraints and retain intent form, scheme, '
        'width, depth, storeys, seed and detail_profile. No unrelated control candidate. '
        'parameters may contain ONLY bay_pitch (integer 3..12), entrance_fraction (0..1), roof_height '
        '(integer 3..12), chamfer (integer 0..6: cells of pan coupé cut from a corner plot). '
        'Choose coherent variants according to the brief, never arbitrary extremes. '
        'technique_catalogue lists the whole addressable detail vocabulary (families such as '
        'diagonal_corner / quoin / mullion / transom / pediment / balcony_slab, 135 recipe variants, '
        '43 annotated windows, 770 extracted details, 25 audited techniques). NAME the ids this design '
        'should use, layer by layer, and the generator places them verbatim via '
        'technique_library.stamp(scene, id, x, y, z, turns) — states already resolved for pasting with '
        'block updates disabled. A design that never names a technique is a design that will be built '
        'from raw blocks. '
        'rationale explains the allowed architectural difference and its compliance. Fixed user values '
        'must stay identical across candidates. Inspect the active source including task-local extensions '
        'before declaring a capability gap; do not infer model inability from a missing generator feature. '
        'Declare missing geometry as unsupported_decisions for source extension, never silently drop it. '
        'Do not grant architectural or game acceptance.'}
    proposal, receipt = run_json(key, model, json.dumps(payload, ensure_ascii=False), phase='framework_planning',
        context={'generator_sources': {'root': str(snapshot), 'files': list(source_text)},
                 'module_roles': {}, 'failures': {}, 'validation_feedback': None},
        required_tools=('generator_source_map', 'read_generator_source'), emit=emit)
    rows = proposal.get('framework_candidates') or proposal.get('framework_candidate')
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(proposal.get('unsupported_decisions'), list):
        raise ValueError('框架规划需要明确生成器能力缺口列表')
    if not isinstance(rows, list) or len(rows) != 1 or not proposal.get('confirmed_brief'):
        raise ValueError('框架规划需要完整已确认提示词与唯一方案')
    for row in rows:
        parameters = row.get('parameters', {})
        if not isinstance(parameters, dict) or not parameters or not row.get('rationale'):
            raise ValueError('框架变体需要参数及符合提示词的依据')
        for name, value in parameters.items():
            if name == 'entrance_fraction' and isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1:
                continue
            if name in ('bay_pitch', 'roof_height') and type(value) is int and 3 <= value <= 12:
                continue
            # Geometry the planning model is allowed to choose. Without an entry here the
            # only vocabulary it had was three scalars, so a brief asking for a cut corner
            # (pan coupé) could not be expressed at all.
            if name == 'chamfer' and type(value) is int and 0 <= value <= 6:
                continue
            raise ValueError('框架变体修改了锁定参数或使用不支持的参数：' + name)
    language = proposal.get('architectural_contract')
    if not isinstance(language, dict) or not language.get('style') or not language.get('invariants'):
        raise ValueError('框架规划缺少建筑规制')
    task['brief'].update(use=proposal['confirmed_brief'], confirmed_brief=proposal['confirmed_brief'],
                         style=language['style'], design_language=language)
    task['framework_proposals'] = rows
    task['framework_policy'] = 'prompt-bound-v1'
    task['pending_capability_gaps'] = proposal.get('unsupported_decisions', [])
    task['history'].append({'framework_contract': proposal, 'receipt': receipt})
    # The framework contract IS the agent's reading of the brief: the prompt it
    # reconstructed, the architectural rules it derived, the candidates it proposes and
    # the generator capabilities it declares missing. That reasoning belongs on the page.
    if emit:
        emit('agent_progress', {'summary': '已确认提示词：' + str(proposal.get('confirmed_brief'))[:400]})
        emit('agent_progress', {'summary': '建筑规制：风格=%s｜不变量=%s' % (
            language.get('style'),
            json.dumps(language.get('invariants'), ensure_ascii=False)[:320])})
        for row in rows:
            emit('agent_progress', {'summary': '候选 %s：%s' % (
                json.dumps(row.get('parameters'), ensure_ascii=False),
                str(row.get('rationale'))[:160])})
        for gap in (proposal.get('unsupported_decisions') or []):
            emit('agent_progress', {'summary': '能力缺口：' + str(gap)[:200]})
    task['selected'] = {}
    w.rollback(task, 'frameworks', 'Bind every framework candidate to the complete confirmed user brief.')


def candidate(task, folder, ident, spec, size, emit=None):
    folder.mkdir(parents=True, exist_ok=True)
    stage = task['stage']
    tier = {'frameworks': 0, 'facades': 1, 'tier2': 2, 'tier3': 3}[stage]
    operation = Operation('build.' + stage, {'candidate': ident, 'plan': spec, 'tier': tier,
                          'run': Path(task['path']).parent.name, 'revision': task['revision']},
                          evidence=task['intent'].get('evidence_ids', []), emit=emit)
    try:
        schematic = folder / 'candidate.schem'
        if task.get('generator_version'):
            from .generator_repair import worker
            generated = worker(task['generator_version'], 'build', spec, tier, folder)
            if generated['status'] != 'PASS':
                raise ValueError('修复版生成器构建失败：' + generated.get('log', '')[-1000:])
            manifest = read_json(folder / 'manifest.json')
            same = generated['deterministic']
        else:
            plan = design.plan_for(**spec)
            scene, manifest = design.build(plan, tier=tier)
            write_schematic(schematic, scene.volume, scene.palette, name='Atelier ' + stage)
            repeat, _ = design.build(plan, tier=tier)
            same = bool(np.array_equal(np.array(scene.palette)[scene.volume], np.array(repeat.palette)[repeat.volume]))
        read = load_schematic(schematic)
        validation = read.validation()
        geometry = inspect_geometry(read, decorative_doors=manifest.get('decorative_doors', []))
        # The independent registry check shells out to node. A timeout there used to raise
        # straight out of the run and kill it; treat it as a FAILED CHECK FOR THIS
        # CANDIDATE instead, so one slow node process cannot end an otherwise progressing
        # repair loop.
        try:
            registry = subprocess.run([node_binary(), str(ROOT / 'tools/validate_schematic.cjs'), str(schematic),
                str(folder / 'registry.json')], capture_output=True, text=True, encoding='utf-8',
                errors='replace', timeout=300)
            registry_code = registry.returncode
        except subprocess.TimeoutExpired:
            registry_code = -1
        technical = {'status': 'PASS' if validation['status'] == geometry['status'] == 'PASS' and same and registry_code == 0 else 'FAIL',
                     'file_validation': validation, 'geometry': geometry, 'deterministic_rebuild': same,
                     'independent_registry': read_json(folder / 'registry.json') if (folder / 'registry.json').exists() else {'status': 'FAIL'},
                     'generator_version': task.get('generator_version'), 'game_acceptance': 'PENDING'}
        # A manifest may DECLARE a capability that the exported building does not contain:
        # a live generator imported the technique registry, stored an unused count, and
        # recorded `technique_library_stamp_dispatch: active` with zero library blocks in
        # the geometry. Importing a name is not using it, so the claim is audited against
        # the artifact here.
        #
        # An unbacked claim is CORRECTED, not treated as a build failure. Failing the build
        # would deadlock the run on a paperwork field while the real geometry defects still
        # needed their own repair rounds; rewriting the claim to what the audit measured
        # guarantees a false claim can never reach the deliverable and keeps the honest
        # finding in the technical record. The generator is still told to make the claim
        # true — see the repair instruction — but nothing ships a lie either way.
        from . import technique_library
        audit = technique_library.verify_stamp_audit(read, manifest.get('stamp_audit'))
        claimed = next((row for row in (manifest.get('unsupported_decisions') or [])
                        if isinstance(row, dict) and row.get('id') == 'technique_library_stamp_dispatch'), None)
        unbacked = bool(claimed and claimed.get('status') == 'active' and not audit['matched_cells'])
        if unbacked:
            claimed['status'] = 'not_applicable'
            claimed['reason'] = ('Audited against the exported schematic: no declared library stamp has a single '
                                 'matching cell, so this capability is recorded as not_applicable. Prior claim: '
                                 + str(claimed.get('reason'))[:300])
        technical['stamp_audit'] = {**audit, 'manifest_claim': (claimed or {}).get('status'),
                                    'claim_corrected': unbacked,
                                    'claim_backed_by_geometry': bool(audit['matched_cells'])}
        record(task, folder, 'technical_validation', technical, ident)
        if technical['status'] != 'PASS':
            raise ValueError('Candidate technical validation failed: ' + str(ident))
        w.register_artifact(task, 'schematic', schematic, ident)
        record(task, folder, 'facade_section', measure_facade_section(schematic), ident)
        concept = {**spec, 'footprint_type': spec['form'], 'massing_seed': spec['seed'],
                   'facade_seed': spec['seed'], 'detail_seed': spec['seed'],
                   'techniques': manifest['techniques'], 'scope': 'No dressing at framework stage'}
        if stage == 'frameworks' and task.get('framework_proposals'):
            concept['design_rationale'] = task['framework_proposals'][int(ident.split('-')[1]) - 1]['rationale']
            concept['confirmed_brief'] = task['brief'].get('confirmed_brief')
        record(task, folder, 'concept' if stage == 'frameworks' else 'assembly_plan', concept, ident)
        write_json(folder / 'manifest.json', manifest)
        # The seven fixed views carry the structural evidence. The sixteen orbit frames
        # are the same building photographed from other angles: they added no structural
        # evidence, yet every review round paid a full model-vision pass for them — the
        # single biggest reason a repair round took ~26 minutes. At frameworks the gate
        # only ever judges the envelope, so render and register the seven and leave the
        # orbit set to the stages that actually judge finish.
        structural = stage == 'frameworks'
        images = render_previews(schematic, folder / 'previews', max_size=size,
                                 orbit=not structural)
        # `fixed_view_bundle` is the existing reduced-view contract (the gate reads the
        # `reduced` view_set and only demands observations for the images that exist).
        # Feeding the seven-view render into `view_bundle` raised KeyError on
        # 'orbit_street_000', because that function maps the full protocol set.
        bundle = fixed_view_bundle(images) if structural else view_bundle(images)
        record(task, folder, 'views', bundle, ident,
               view_set='reduced' if structural else None)
        operation.finish({'candidate': ident, 'stage': stage, 'plan': spec,
                          'design_rationale': concept.get('design_rationale'), 'confirmed_brief': task['brief'].get('confirmed_brief')},
                         artifacts=[schematic, folder / 'technical_validation.json', folder / 'views.json'], validation=technical)
    except Exception as error:
        operation.fail(str(error))
        raise


def ensure_section_evidence(task):
    """Add measured evidence to reusable candidates without changing their exports."""
    w._check_hashes(task)
    artifacts = w.current_artifacts(task)
    for artifact in artifacts:
        if artifact['kind'] != 'schematic':
            continue
        existing = next((a for a in artifacts if a['kind'] == 'facade_section'
                         and a['candidate'] == artifact['candidate']), None)
        if existing:
            section = read_json(existing['path'])
            if section['source']['sha256'] != artifact['sha256']:
                raise ValueError('Section evidence is bound to a different schematic')
        else:
            path = Path(artifact['path'])
            record(task, path.parent, 'facade_section', measure_facade_section(path), artifact['candidate'])


def build_stage(folder, size=640, progress=None, emit=None):
    folder = Path(folder)
    task = load(folder)
    w._check_hashes(task)
    ensure_section_evidence(task)
    if task['stage'] not in STAGES:
        raise ValueError('当前阶段不能构建：' + task['stage'])
    target = folder / ('revision-' + str(task['revision'])) / task['stage']
    if task['stage'] == 'delivery':
        return deliver(task, folder, target)
    options = plans(task)
    for position, (ident, spec) in enumerate(options):
        checkpoint()
        if progress:
            progress({'stage': task['stage'], 'candidate': ident, 'completed': position,
                      'total': len(options), 'summary': '正在生成并校验候选，然后渲染全部视角'})
        out = target / (ident or 'selected')
        # Existing completed candidates are reusable only under the unchanged hash bindings.
        existing = [a for a in w.current_artifacts(task) if a['candidate'] == ident]
        if w.REQUIRED[task['stage']] <= {a['kind'] for a in existing}:
            continue
        if out.exists():
            attempt = 2
            while out.with_name(out.name + '-attempt-' + str(attempt)).exists():
                attempt += 1
            out = out.with_name(out.name + '-attempt-' + str(attempt))
        candidate(task, out, ident, spec, size, emit=emit)
    if progress:
        progress({'stage': task['stage'], 'completed': len(options), 'total': len(options),
                  'summary': '候选已就绪，等待视觉评审'})
    task['awaiting'] = 'VISUAL_REVIEW'
    w.save(task)
    return {'run': folder.name, 'stage': task['stage'], 'status': 'AWAITING_VISUAL_REVIEW'}


def deliver(task, folder, target):
    if task['stage'] != 'delivery':
        raise ValueError('Delivery requires all visual gates')
    w._check_hashes(task)
    target.mkdir(parents=True, exist_ok=True)
    op = Operation('delivery', {'run': folder.name, 'revision': task['revision']})
    try:
        source = next(a for a in reversed(task['artifacts']) if a['stage'] == 'tier3' and a['kind'] == 'schematic')
        shutil.copyfile(source['path'], target / 'candidate.schem')
        if task.get('generator_version'):
            from .generator_repair import worker
            out = target / 'versioned-state-lab'
            generated = worker(task['generator_version'], 'state_lab', task['selected']['facades']['plan'], 3, out)
            if generated['status'] != 'PASS': raise ValueError('修复版状态实验件生成失败')
            if load_schematic(out / 'candidate.schem').voxel_state_hash() != load_schematic(target / 'candidate.schem').voxel_state_hash():
                raise ValueError('状态实验件与已审核建筑的生成器版本不一致')
            shutil.copyfile(out / 'STATE-LAB.schem', target / 'STATE-LAB.schem')
            plots = generated['plots']
        else:
            scene, _ = design.build(design.plan_for(**task['selected']['facades']['plan']), tier=3)
            plots = state_lab(scene, target)
        technical = read_json(next(a['path'] for a in task['artifacts'] if a['stage'] == 'tier3' and a['kind'] == 'technical_validation'))
        record(task, target, 'technical_validation', technical)
        w.register_artifact(task, 'schematic', target / 'candidate.schem')
        w.register_artifact(task, 'state_lab', target / 'STATE-LAB.schem')
        record(task, target, 'instructions', {'minecraft_version': '1.21.11', 'data_version': 4671,
            'state_plots': plots, 'steps': ['使用 WorldEdit/FAWE 粘贴状态实验件，记录具体版本与更新开关',
                '对比正常更新与禁止更新；记录相邻变化、区块重载与各方向外观',
                '建筑候选使用禁止更新模式粘贴；只有用户可提交游戏验收'], 'game_acceptance': 'PENDING'})
        record(task, target, 'manifest', {'run': folder.name, 'brief': task['brief'],
            'selected': task['selected'], 'files': [file_receipt(target / name) for name in ('candidate.schem', 'STATE-LAB.schem')],
            'status': 'GAME_CANDIDATE', 'game_acceptance': 'PENDING'})
        measured_advance(task, 'All stage reviews and bound files passed; paired building/state experiments packaged for user-only game acceptance.')
        write_json(target / 'workflow_snapshot.json', task)
        with zipfile.ZipFile(folder / 'delivery.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in target.rglob('*'):
                if path.is_file():
                    archive.write(path, path.relative_to(target))
        op.finish(w.status(task), artifacts=[folder / 'delivery.zip'], validation={'technical': 'PASS', 'game': 'PENDING'})
        return {'run': folder.name, 'stage': 'game', 'status': 'AWAITING_GAME_ACCEPTANCE'}
    except Exception as error:
        op.fail(str(error))
        raise


def submit_review(folder, review):
    task = load(folder)
    if task['stage'] not in ('frameworks', 'facades', 'tier2', 'tier3'):
        raise ValueError('当前阶段不接受视觉评审')
    # Caller supplies the exact revision/hashes from the displayed review template.
    review = {**review, 'reviewer': 'website-operator', 'reviewer_type': 'operator'}
    w.submit_review(task, review)
    if review['decision'] == 'reject':
        w.rollback(task, review['rollback_stage'], review['rationale'])
        for stage in list(task['selected']):
            if w.STAGES.index(stage) >= w.STAGES.index(task['stage']):
                del task['selected'][stage]
        w.save(task)
        return w.status(task)
    if task['stage'] in ('frameworks', 'facades'):
        chosen = next(spec for ident, spec in plans(task) if ident == review['selected'])
        task['selected'][task['stage']] = {'candidate': review['selected'], 'plan': chosen}
    w.advance(task)
    return w.status(task)


def summary(folder):
    task = load(folder)
    artifacts = w.current_artifacts(task)
    candidates = []
    for artifact in artifacts:
        if artifact['kind'] != 'views':
            continue
        candidate_id = artifact['candidate']
        concept = next((a for a in artifacts if a['candidate'] == candidate_id and a['kind'] in ('concept', 'assembly_plan')), None)
        if concept is None:
            continue
        manifest_path = Path(artifact['path']).parent / 'manifest.json'
        candidates.append({'id': candidate_id, 'plan': read_json(concept['path']), 'views': read_json(artifact['path']),
                           'manifest': read_json(manifest_path) if manifest_path.exists() else {},
                           'facade_section': read_json(manifest_path.parent / 'facade_section.json')
                           if (manifest_path.parent / 'facade_section.json').exists() else None})
    references = sorted((ROOT.parent / '参考图').glob('标准*.png'))
    references += sorted((ROOT.parent / '参考图').glob('窗对照总览_街面.png'))
    review = {'stage': task['stage'], 'revision': task['revision'], 'artifact_hashes': w.bindings(task),
              'decision': 'reject', 'rationale': '', 'rollback_stage': task['stage'],
              'selected': candidates[0]['id'] if candidates else None,
              'candidates': [{'id': item['id'], 'decision': 'reject', 'scores': [0, 0, 0, 0, 0],
                              'view_observations': {view: '' for view in item['views']},
                              'reference_comparison': {path.name: '' for path in references},
                              'layer_checks': {key: {'status': '', 'observation': ''} for key in w.LAYER_CHECKS},
                              'geometry_checks': {key: {'status': '', 'observation': ''} for key in w.GEOMETRY_CHECKS},
                              'detail_checks': {layer: {key: {'status': '', 'observation': ''} for key in w.DETAIL_CHECKS}
                                                for layer in w.LAYER_CHECKS[:5]},
                              'storey_checks': {str(i): {key: {'status': '', 'observation': ''} for key in w.DETAIL_CHECKS}
                                                for i in range(item['plan'].get('storeys', 0))},
                              'failure_modes': []} for item in candidates]}
    expected = len(plans(task)) if task['stage'] in ('frameworks', 'facades', 'tier2', 'tier3') else 0
    ready = bool(expected and len(candidates) == expected)
    preview = candidates[0]['views'] if candidates else {}
    if task['stage'] in ('game', 'accepted', 'delivery'):
        last_views = next((a for a in reversed(task['artifacts']) if a['stage'] == 'tier3' and a['kind'] == 'views'), None)
        if last_views:
            preview = read_json(last_views['path'])
    status = w.status(task)
    status['awaiting'] = (task.get('awaiting') if str(task.get('awaiting', '')).startswith('AGENT_') else
                          'GAME_ACCEPTANCE' if task['stage'] == 'game' else
                          'VISUAL_REVIEW' if ready else None)
    return {'status': w.status(task), 'candidates': candidates, 'review_template': review,
            'selected': task['selected'], 'history': task['history'], 'brief': task['brief'],
            'references': [str(p.relative_to(ROOT.parent)) for p in references],
            'delivery': (Path(folder) / 'delivery.zip').exists() and task['stage'] in ('game', 'accepted'),
            'status': status, 'ready_for_review': ready, 'preview': preview,
            'review_policy': task.get('review_policy', 'legacy'),
            'execution_mode': task.get('execution_mode', 'manual'),
            'delivery_files': {kind: str(Path('revision-' + str(task['revision'])) / 'delivery' / name)
                               for kind, name in [('building', 'candidate.schem'), ('state_lab', 'STATE-LAB.schem'),
                                                  ('instructions', 'instructions.json')]}}


def agent_review(folder, key, model, emit=None):
    from .providers import MultimodalClient, ProviderError
    task = load(folder)
    ensure_section_evidence(task)
    data = summary(folder)
    client = MultimodalClient({'model': 'deepseek-flash', 'base_url': 'https://api.deepseek.com',
        'vision': True, 'max_calls': None, 'max_total_tokens': None, 'max_output_tokens': 16000,
        'timeout_seconds': 180, 'request_options': {'thinking': {'type': 'disabled'}}}, credential=key)
    rows = []
    receipts = []
    for candidate, template in zip(data['candidates'], data['review_template']['candidates']):
        operation = Operation('vision.' + task['stage'], {'candidate': candidate['id'],
            'plan': candidate['plan'], 'revision': task['revision']}, emit=emit)
        client.config['raw_reply_dir'] = str(operation.folder)
        try:
            images = [Path(item['path']) for item in candidate['views'].values()]
            images += [ROOT.parent / path for path in data['references']]
            scope = {'frameworks': 'ONLY judge the bare structural envelope, dimensions, roof mass, opening grid and street/party-wall topology. '
                     'Facade dressing is not yet built: absence of shopfront decorations, surrounds, balconies, cornice mouldings, dormer decoration, '
                     'stone bands and differentiated window dressing MUST NOT be failure modes or reduce scores. Layer checks of dressing are not_applicable. '
                     'The five scoring axes here mean plot fit, envelope closure, mass proportions, opening-grid hierarchy, and all-direction structural readability.',
                     'facades': 'Judge ELEVATION COMPOSITION only: opening hierarchy and bay rhythm, storey height grading, '
                     'window surrounds and sills, string courses and the cornice line, chamfer composition, and party-wall correctness. '
                     'This stage builds composition, NOT the full detail vocabulary. The following are later tier2/tier3 work, and their '
                     'absence MUST NOT be a failure mode and MUST NOT reduce any score: iron railings and balcony guard rails, '
                     'console/corbel repeat units under the cornice, shopfront dressing and sign bands, rustication, quoins, '
                     'dormer joinery, cresting, and material-state variation. Mark the layer and detail checks for those elements '
                     'not_applicable with a reason instead of failing them. The five scoring axes here mean plot fit, elevation '
                     'composition, opening-grid hierarchy, cornice and band articulation, and all-direction facade readability.',
                     'tier2': 'Judge every built detail on every facade layer: openings, window shapes and joinery, surrounds, sills, lintels, '
                              'doors, shopfronts, balconies, bands, cornice, attic and roof details, materials and junctions. '
                              'Final guard rails, rustication, quoins and cresting are tier3 work; their absence alone is not a defect.',
                     'tier3': 'Judge the complete visible building, all layers, all directions and roof. Reject concrete visible defects.'}[task['stage']]
            scope += (' Plot topology: street_house has one street face, one courtyard rear and two intentionally blind party walls; '
                      'corner_house has two adjacent street faces and two blind party walls. Blind party walls are correct, '
                      'not missing windows or missing corner composition. Street-plane balcony ends visible in a side '
                      'projection are not openings through the party wall. Corner composition is not_applicable for street_house. '
                      'Judge visible geometry against this plan and stage, without assuming all four sides must be decorated street facades. '
                      'A perspective may hide chimneys, dormers and windows; different visible counts are not evidence that '
                      'the actual building changes between cameras. References include multi-building streets; compare '
                      'their architectural vocabulary, not their total number of buildings or corner topology.')
            if task['stage'] in ('frameworks', 'facades'):
                scope += ' Entrance portals are intentionally unfilled at this stage; functional leaves and transoms are added later.'
            scope += (' Architectural style is an acceptance constraint, not a colour palette. At FRAMEWORKS '
                      'resolve body proportions, floor hierarchy, opening rhythm, attic volume and especially the actual roof SECTION '
                      'against the requested architectural type, design language and reference. For a mansard requirement, explicitly locate the steep '
                      'lower slope, slope break and shallower upper slope; a simple triangular gable with dark tiles/dormers/chimneys '
                      'does not prove mansard form. Other historical roof types need a cited justification compatible with the brief. '
                      'Use side/high/top views and geometric section data; record uncertainty as fail rather than guessing pass. '
                      'Decoration is not a substitute for structural form. If later detail work exposes a structural mismatch, '
                      'reject and request rollback to frameworks. At TIER2 and TIER3 only — never at frameworks or facades — inspect '
                      'each floor separately, including '
                      'all its windows, doors, surrounds, sills, lintels, balcony relationships, bands, cornice and material junctions; '
                      'use not_applicable only for elements genuinely absent by design or reserved for a future tier, with a reason.')
            scope += (' The brief design_language is authoritative: apply its architectural invariants and '
                      'relationships while preserving its allowed variation. Style-specific roof and facade rules '
                      'apply only when required by that brief. A design is not a literal copy of reference coordinates. '
                      'The five reference images are EXEMPLARS of good facade work and a source of learnable technique, '
                      'NOT the acceptance standard: judge against the brief and the operator requirements. Never fail a '
                      'candidate merely for differing from a reference image, and never pass one merely for resembling it.')
            if task['stage'] in ('frameworks', 'facades'):
                scope += (' Judge whether the detail vocabulary is correctly BEGUN at this stage, not whether it is complete: '
                          'openings are recessed rather than surface-painted, surrounds and sills exist where the plan calls for them, '
                          'and the storey hierarchy is legible. The full vocabulary — mullions and transoms, shopfronts with sign '
                          'bands, railings, rustication, quoins, dormers and roof junctions — is judged at tier2 and tier3. At '
                          'frameworks and facades its absence is NOT a defect, NOT a failure mode, and must not lower any score.')
            else:
                scope += (' Judge whether the detail vocabulary is actually used — recessed openings with '
                          'surrounds, sills and lintels, mullions and transoms, cornice and string courses, shopfronts with '
                          'sign bands, railings, rustication, quoins, dormers and roof junctions — and whether those choices '
                          'follow the storey hierarchy rather than being spread uniformly.')
            scope += (' The facade_section report is independent measurement of the EXACT exported schematic, bound by SHA256. '
                      'For opening counts, voxel recess depths, course coverage, corner alignment and roof heights, use these '
                      'measurements before manifest prose or occluded pixel observations. Occlusion alone is not a failure '
                      'when the measured property is established. A measured contradiction IS a failure; unmeasured or unsupported '
                      'properties remain uncertain and must not be guessed pass or marked not_applicable. Never extend a measurement '
                      'to an unmeasured attribute. The NE street corner and SW blind-wall corner are different physical corners. '
                      'Floor indices are zero-based and floors_y comes from measured floor plates. Report limits, gaps and spikes honestly.')
            section = section_review_evidence(candidate['facade_section'])
            batches = []
            def checked_call(label, payload, paths, validator):
                # The verdict batch is a cheap text-only call, while every other batch has
                # already spent real vision calls by the time it returns. Losing a whole
                # review to one malformed verdict reply is the wrong trade, so the verdict
                # gets more attempts than the image batches.
                #
                # Retries also have to outlast a real network wobble. A one-second pause
                # recovered format mistakes but not a provider that closed the connection:
                # a live run stopped four times in a row inside one such window, and every
                # failure threw away a review that had already paid for its vision calls.
                limit = 5 if label == 'verdict' else 4
                for attempt in range(limit):
                    checkpoint()
                    try:
                        budget = 16000 if label == 'verdict' and task['stage'] != 'frameworks' else 8000
                        result, receipt = client.complete(json.dumps(payload, ensure_ascii=False), images=paths, max_tokens=budget)
                        checkpoint()
                        write_json(operation.folder / (label + '-' + str(attempt) + '.json'), {'result': result, 'receipt': receipt})
                        if not validator(result): raise ValueError('视觉批次输出不完整：' + label)
                        batches.append(receipt)
                        return result
                    except (ProviderError, ValueError) as error:
                        operation.event({'batch': label, 'attempt': attempt + 1, 'error': str(error)})
                        if attempt == limit - 1: raise
                        payload['format_reminder'] = ('Previous output failed validation: ' + str(error) +
                            '. Follow required_output and the requested field names/types exactly. No markdown.')
                        time.sleep(min(30, 4 * (attempt + 1)))
            observations = {}
            view_items = list(candidate['views'].items())
            for offset in range(0, len(view_items), 7):
                batch = view_items[offset:offset+7]
                result = checked_call('views-' + str(offset), {'stage_scope': scope, 'brief': task['brief'],
                    'plan': candidate['plan'], 'structure': candidate.get('manifest', {}).get('structure'),
                    'walls': candidate.get('manifest', {}).get('walls'),
                    'facade_section': section,
                    'views_in_order': [name for name, _ in batch],
                    'instruction': 'Inspect every image in order. Return JSON observations: an array of exactly '
                    + str(len(batch)) + ' concise Chinese strings, one concrete pixel observation per image. Do not score or approve.'},
                    [Path(item['path']) for _, item in batch],
                    lambda value: isinstance(value.get('observations'), list) and len(value['observations']) == len(batch)
                        and all(isinstance(text,str) and text.strip() for text in value['observations']))
                observations.update(dict(zip([name for name, _ in batch], result['observations'])))
            reference_result = checked_call('references', {'candidate_observations': observations, 'brief': task['brief'],
                'facade_section': section,
                'required_output': {'comparisons': ['One nonempty comparison string per reference image, in image order']},
                'stage_scope': scope, 'instruction': 'Inspect these five reference images in order. Return JSON comparisons: '
                'an array of exactly five concise Chinese comparisons to the supplied candidate observations.'},
                [ROOT.parent / path for path in data['references']],
                lambda value: normalize_reference_comparisons(value, len(data['references'])))
            verdict = collect_architectural_verdict(task, {'stage_scope': scope, 'brief': task['brief'], 'plan': candidate['plan'],
                'structure': candidate.get('manifest', {}).get('structure'), 'walls': candidate.get('manifest', {}).get('walls'),
                'openings': candidate.get('manifest', {}).get('openings'),
                'facade_section': candidate['facade_section'],
                'observations': observations, 'reference_comparisons': reference_result['comparisons']}, checked_call)
            row = {'id': candidate['id'], 'decision': verdict['decision'], 'scores': verdict['scores'],
                'view_observations': observations,
                'reference_comparison': dict(zip(template['reference_comparison'], reference_result['comparisons'])),
                'layer_checks': dict(zip(w.LAYER_CHECKS, verdict['layers'])), 'failure_modes': verdict['failure_modes']}
            for field in ('geometry_checks', 'detail_checks', 'storey_checks'):
                if field in verdict: row[field] = verdict[field]
            groups = ([row.get('geometry_checks', {})] + list(row.get('detail_checks', {}).values())
                      + list(row.get('storey_checks', {}).values()))
            if any(check['status'] == 'fail' for group in groups for check in group.values()):
                row['decision'] = 'reject'
            if any(check['status'] == 'fail' for check in verdict['layers']): row['decision'] = 'reject'
            receipt = {'model':'deepseek-flash', 'batches':batches}
            rows.append(row); receipts.append(receipt)
            operation.finish({'review': row, 'receipt': receipt}, artifacts=images,
                             validation={'image_input': 'ACTUAL', 'game_acceptance': 'PENDING'})
        except Exception as error:
            operation.fail(str(error)); raise
    eligible = [row for row in rows if row['decision'] == 'pass' and
                (task['stage'] != 'frameworks' or w.score_gate_failure(row.get('scores'), w.score_profile(task)) is None)]
    chosen = max(eligible, key=lambda row: sum(row.get('scores', []))) if eligible else None
    review = {'decision': 'pass' if chosen else 'reject', 'selected': chosen['id'] if chosen else None,
        'rationale': 'AI 实际查看全部候选视图及标准图后比较，选择满足阶段门槛且评分最高的候选。' if chosen else '当前候选均未通过 AI 逐图视觉评审。',
        'candidates': rows, 'stage': task['stage'], 'revision': task['revision'],
        'artifact_hashes': w.bindings(task), 'reviewer': model, 'reviewer_type': 'agent',
        'scope': 'actual_multimodal_visual_review', 'game_acceptance': 'PENDING',
        'rollback_stage': task['stage'], 'receipts': receipts}
    # Every stage's verdict reaches the page, not only the repair stage: the reviewer's
    # per-candidate failure reasons ARE the reasoning behind a pass or a rollback, and
    # until now they stayed inside the review record where the UI could not see them.
    if emit:
        for row in rows:
            head = '评审 %s：%s' % (row['id'], '通过' if row['decision'] == 'pass' else '未通过')
            if row.get('scores'):
                head += '｜评分 %s' % (row['scores'],)
            emit('agent_progress', {'summary': head})
            for failure in (row.get('failure_modes') or [])[:4]:
                emit('agent_progress', {'summary': '　· %s' % str(failure)[:200]})
        emit('agent_progress', {'summary': '阶段结论：' + str(review['rationale'])[:200]})
    w.submit_review(task, review)
    if review['decision'] != 'pass':
        raise ValueError('Agent 阶段检查未通过：' + str(review['rationale']))
    if task['stage'] in ('frameworks', 'facades'):
        chosen = next(spec for ident, spec in plans(task) if ident == review['selected'])
        task['selected'][task['stage']] = {'candidate': review['selected'], 'plan': chosen}
    w.advance(task)
    return w.status(task)


def collect_architectural_verdict(task, evidence, checked_call):
    """Collect bounded schema groups without dropping any architectural review gate."""
    section = evidence.get('facade_section')
    if section:
        evidence = {**evidence, 'facade_section': section_review_evidence(section)}
    def check_item(item, allow_na=True):
        return (isinstance(item, dict) and item.get('status') in
                (('pass', 'fail', 'not_applicable') if allow_na else ('pass', 'fail'))
                and isinstance(item.get('observation'), str) and bool(item['observation'].strip()))

    def group_valid(value, keys, allow_na=True):
        group = value.get('checks')
        if not isinstance(group, dict) or set(group) != set(keys):
            raise ValueError('checks 必须完整包含：' + ', '.join(keys))
        for key in keys:
            if not check_item(group[key], allow_na):
                raise ValueError('checks.' + key + ' 需要 status 和非空 observation 对象')
        return True

    result = {}
    if task['stage'] == 'frameworks':
        groups = [('geometry', w.GEOMETRY_CHECKS, False)]
    else:
        groups = [('layer-' + layer, w.DETAIL_CHECKS, True) for layer in w.LAYER_CHECKS[:5]]
        groups += [('storey-' + str(i), w.DETAIL_CHECKS, True)
                   for i in range(task.get('intent', {}).get('storeys', evidence['plan'].get('storeys', 0)))]
    for label, keys, allow_na in groups:
        statuses = 'pass|fail|not_applicable' if allow_na else 'pass|fail'
        group_evidence = evidence
        if section and label.startswith('storey-'):
            group_evidence = {**evidence, 'facade_section': section_review_evidence(section, int(label[7:]))}
        response = checked_call('checks-' + label, {**group_evidence, 'review_group': label,
            'required_output': {'checks': {key: {'status': statuses, 'observation': '具体视图/剖面依据'} for key in keys}},
            'instruction': 'Inspect ONLY this review_group in the CURRENT stage scope. Return checks with exactly '
            'the required keys. Each check must be an object with status and a concrete Chinese observation. '
            'For storey-N inspect that individual floor (0 is ground); for layer-X cover all actual floors '
            'belonging to that layer. Inspect every window and junction. For geometry roof_section describe '
            'the required roof type and evidence/uncertainty; for a mansard requirement describe '
            'steep lower slope, slope break and shallower upper slope. '
            'For each measured attribute cite facade_section coordinates, floor index and actual values. '
            'Respect measurement limits. Manifest text is an unverified claim. For window edges, balcony parts and junctions '
            'use the per-position surface maps (palette IDs, depth -3 outside through +3 inside); assess each opening, '
            'not only the average floor. Never approve missing evidence or future-tier decorations.'}, [],
            lambda value: group_valid(value, keys, allow_na))
        if label == 'geometry': result['geometry_checks'] = response['checks']
        elif label.startswith('layer-'): result.setdefault('detail_checks', {})[label[6:]] = response['checks']
        else: result.setdefault('storey_checks', {})[label[7:]] = response['checks']

    def summary_valid(value):
        # Return a DESCRIPTION of the first violation instead of a bare False: the retry
        # reminder quotes it back to the model, and a generic "incomplete" reminder let a
        # live run fail the verdict batch three times in a row, killing the run. The
        # observed mistake was concrete — seven scores, one per layer, instead of five
        # scoring axes — and naming it is what lets the next attempt succeed.
        if value.get('decision') not in ('pass', 'reject'):
            raise ValueError('decision must be exactly "pass" or "reject"')
        scores = value.get('scores')
        if not isinstance(scores, list) or len(scores) != 5:
            raise ValueError('scores must be a list of EXACTLY 5 numbers (one per scoring axis), got %s'
                             % (len(scores) if isinstance(scores, list) else type(scores).__name__))
        if not all(type(score) in (int, float) and 0 <= score <= 20 for score in scores):
            raise ValueError('every one of the 5 scores must be a number from 0 to 20')
        layers = value.get('layers')
        if not isinstance(layers, list) or len(layers) != len(w.LAYER_CHECKS):
            raise ValueError('layers must be a list of EXACTLY %d objects in layer_order, got %s'
                             % (len(w.LAYER_CHECKS), len(layers) if isinstance(layers, list) else type(layers).__name__))
        if not all(check_item(item) for item in layers):
            raise ValueError('every layer needs an object with status pass|fail|not_applicable and a nonempty observation')
        modes = value.get('failure_modes')
        if not isinstance(modes, list) or not modes:
            raise ValueError('failure_modes must be a nonempty list of strings')
        if not all(isinstance(text, str) and text.strip() for text in modes):
            raise ValueError('every failure_modes entry must be a nonempty string')
        return True

    verdict_instruction = (
        'Summarize the completed checks using ONLY required_output fields. '
        'TWO DIFFERENT LISTS, DO NOT MERGE THEM: "scores" is EXACTLY 5 numbers, one per scoring axis from '
        'score_policy — it is NOT one score per layer, and 7 scores is always wrong. "layers" is EXACTLY '
        '%d objects in layer_order, one per building layer. '
        'Six or eight scores, or a scores list copied from the layers, fails validation. '
        'Any failed architectural check requires reject. '
        'Do not repeat detail_checks/storey_checks/geometry_checks. Never grant game acceptance.'
        % len(w.LAYER_CHECKS))

    summary = checked_call('verdict', {**evidence, 'completed_checks': result,
        'layer_order': list(w.LAYER_CHECKS), 'score_policy': w.score_profile(task),
        'required_output': {'decision': 'pass|reject', 'scores': [0, 0, 0, 0, 0],
            'layers': [{'status': 'pass|fail|not_applicable', 'observation': layer + ' 的具体观察'} for layer in w.LAYER_CHECKS],
            'failure_modes': ['具体缺陷；无缺陷时明确写无']},
        'instruction': verdict_instruction}, [], summary_valid)
    result.update({key: summary[key] for key in ('decision', 'scores', 'layers', 'failure_modes')})
    if not architectural_result_valid(task, result):
        raise ValueError('分批建筑审核未满足完整门槛')
    return result


def normalize_reference_comparisons(value, count):
    rows = value.get('comparisons', value.get('references'))
    if not isinstance(rows, list) or len(rows) != count:
        return False
    normalized = []
    for row in rows:
        if isinstance(row, str) and row.strip():
            normalized.append(row)
        elif isinstance(row, dict) and any(isinstance(row.get(key), str) and row[key].strip()
                                         for key in ('comparison', 'agreement', 'conflict')):
            # Preserve structured observations verbatim rather than dropping their evidence.
            normalized.append(json.dumps(row, ensure_ascii=False))
        else:
            return False
    value['comparisons'] = normalized
    return True


def architectural_result_valid(task, result):
    try:
        # A failing check is a valid review result, but can never approve a candidate.
        w.validate_architectural_checks(task, {**result, 'decision': 'reject'})
        return True
    except ValueError:
        return False


def run_autonomous(folder, key, model, emit=None, progress=None):
    task = load(folder)
    prepare_framework_contract(task, folder, key, model, emit)
    if task.get('review_policy') == 'layered-v1' and task['stage'] in STAGES:
        w.rollback(task, 'frameworks', 'Previous reviews lack explicit roof-form and per-storey detail evidence.')
        task['selected'] = {}
        task['review_policy'] = 'layered-v2'
        if emit: emit('agent_progress', {'summary': '旧审核缺少屋顶形制与逐层细节证据，重新从框架门禁核对。'})
    task['execution_mode'] = 'autonomous'
    task['capabilities'].update(image_input=True, model_image_input=True, visual_reviewer='agent')
    w.save(task)
    if task.get('pending_capability_gaps'):
        apply_generator_repair(task, folder, {'stage': task['stage'], 'decision': 'reject', 'candidates': [],
            'requested_extensions': task['pending_capability_gaps'],
            'scope': 'Explicit planning capability gaps, not a visual verdict or approval'}, key, model, emit)
        task = load(folder)
    # New independent evidence invalidates the old rejection bindings, requiring a
    # fresh review of the same geometry before another generator repair.
    ensure_section_evidence(task)
    previous = task['reviews'][-1] if task['reviews'] else {}
    if (previous.get('decision') == 'reject' and previous.get('stage') == task['stage']
            and previous.get('revision') == task['revision'] and previous.get('artifact_hashes') == w.bindings(task)):
        apply_generator_repair(task, folder, previous, key, model, emit)
    #: A repair loop that never converges burns model calls without producing anything:
    #: one live run reached 22 revisions and 21 rewritten generators with no candidate
    #: ever accepted. Cap the consecutive repair rounds per stage and stop for a human
    #: instead of looping forever.
    #: A repair loop that keeps producing NEW generator versions is converging, however
    #: many rounds it takes; one that produces nothing new is stuck. Cap on the latter
    #: (with a generous hard ceiling), not on a fixed round count — a live run was doing
    #: 244→633 and 503→963 character patches every round and would have been cut off.
    hard_limit = 8
    attempts = {}
    seen_versions = set()

    def reviewed():
        """One visual review, retried across transport failures but never across verdicts.

        A review is a dozen vision calls and the verdict is the last of them, so a single
        malformed JSON reply at the end used to destroy the whole review AND the run that
        was driving it (one live run died exactly this way). A provider failure is not an
        architectural verdict: retry it. An `Agent 阶段检查未通过` ValueError IS a verdict
        and must fall straight through to the repair loop below.

        The pauses escalate over roughly two minutes because the failures that matter are
        provider-side windows, not model mistakes: a run that stopped four consecutive
        times was inside one such window that had cleared by the time it was inspected.
        """
        delays = (10, 30, 60, 90)
        for round_index in range(len(delays) + 1):
            try:
                return agent_review(folder, key, model, emit=emit)
            except ValueError:
                raise
            except Exception as error:
                if round_index == len(delays):
                    raise
                if emit:
                    emit('agent_progress', {'summary': '评审批次失败，%d 秒后重试（%d/%d）：%s'
                                            % (delays[round_index], round_index + 1, len(delays),
                                               str(error)[:160])})
                time.sleep(delays[round_index])

    def budget_check(reason_label):
        """Count one repair round and stop the stage when the loop is not converging."""
        failed = load(folder)
        attempts[stage] = attempts.get(stage, 0) + 1
        current = (failed.get('generator_version') or {}).get('id') or 'MAIN'
        stalled = current in seen_versions
        seen_versions.add(current)
        if stalled or attempts[stage] > hard_limit:
            failed['awaiting'] = 'AGENT_BLOCKED_' + stage
            failed['history'].append({'agent_blocked': stage, 'attempts': attempts[stage] - 1,
                'reason': reason_label + ('；生成器版本再无变化，修复未收敛' if stalled else '；超过轮次硬上限'),
                'generator_version': current[:12]})
            w.save(failed)
            raise ValueError('同一阶段已修复 %d 轮且%s（%s），已停下等待人工判断'
                             % (attempts[stage] - 1,
                                '生成器版本再无变化' if stalled else '超过轮次硬上限', stage))
        return failed

    while load(folder)['stage'] in STAGES:
        checkpoint()
        task = load(folder)
        stage = task['stage']
        try:
            result = build_stage(folder, progress=progress, emit=emit)
        except ValueError as error:
            # A candidate that fails its own technical validation is a generator defect —
            # precisely what the repair loop exists for — yet it used to end the run. A
            # manifest that claims a capability the geometry does not contain is caught
            # here, so route the diagnosis into the same repair path a review rejection
            # takes instead of dying.
            if emit:
                emit('agent_progress', {'summary': '候选未通过技术校验，Agent 正在修复生成器：%s'
                                        % str(error)[:180]})
            failed = budget_check('候选技术校验失败')
            apply_generator_repair(failed, folder, {'stage': stage, 'decision': 'reject', 'candidates': [],
                'failure_modes': [str(error)[:400]],
                'scope': 'Technical validation of the BUILT candidate failed. This is a generator defect, '
                         'not a visual verdict: fix the generator so the built artifact itself passes.'},
                key, model, emit)
            continue
        if stage == 'delivery': return result
        if emit: emit('agent_progress', {'summary': 'Agent 正在比较与检查当前阶段：' + stage})
        try:
            result = reviewed()
            attempts[stage] = 0
        except ValueError as error:
            if not str(error).startswith('Agent 阶段检查未通过：'):
                raise
            failed = load(folder)
            last = failed['reviews'][-1] if failed['reviews'] else {}
            if last.get('stage') != stage or last.get('decision') != 'reject':
                raise
            failed = budget_check('视觉评审未通过')
            if emit:
                emit('agent_progress', {'summary': '第 %d 轮修复 %s 阶段（生成器版本在推进，继续）'
                                        % (attempts[stage], stage)})
            apply_generator_repair(failed, folder, last, key, model, emit)
            continue
        except Exception as error:
            # A review that still cannot complete after its retries is an infrastructure
            # stop, not an architectural verdict. Record it as a named blocker so the run
            # can be resumed with its accumulated generator, instead of dying with a bare
            # traceback and a stale `awaiting` field — which is exactly how one live run
            # was lost after a single malformed provider reply.
            failed = load(folder)
            failed['awaiting'] = 'AGENT_REVIEW_ERROR_' + stage
            failed['history'].append({'agent_review_error': stage,
                'error': type(error).__name__ + ': ' + str(error)[:400],
                'generator_version': ((failed.get('generator_version') or {}).get('id') or 'MAIN')[:12]})
            w.save(failed)
            raise ValueError('阶段 %s 的视觉评审重试后仍失败（%s），已记录并停下等待处理'
                             % (stage, type(error).__name__)) from error
        if progress: progress({**result, 'run': Path(folder).name, 'summary': 'Agent 阶段检查已完成，自动继续。'})
    return {'run': Path(folder).name, 'stage': load(folder)['stage']}


def apply_generator_repair(task, folder, review, key, model, emit=None):
    from .generator_repair import repair_generator
    if emit: emit('agent_progress', {'summary': '建筑审核未通过，Agent 正在读取生成器源码并修复。'})
    version, rollback, evidence = repair_generator(task, folder, review, key, model, emit=emit)
    # `generator_version` may be an explicit None (a reset baseline), and a dict.get
    # default does NOT cover a present-but-None value: `task.get(k, {})` still returns
    # None, so the chained .get('id') raised "'NoneType' object has no attribute 'get'".
    # That killed a live run one second AFTER a repair had succeeded.
    if version['id'] == (task.get('generator_version') or {}).get('id'):
        raise ValueError('生成器修复没有改变当前版本，已保存诊断')
    task['generator_version'] = version
    task['pending_capability_gaps'] = []
    for stage in list(task['selected']):
        if w.STAGES.index(stage) >= w.STAGES.index(rollback): del task['selected'][stage]
    task['history'].append({'generator_repair': evidence, 'generator_version': version})
    w.rollback(task, rollback, evidence['proposal']['reason'])
    if emit: emit('agent_progress', {'summary': '生成器源码修复及测试通过，正在用新版本重新生成并审核：' + rollback})
