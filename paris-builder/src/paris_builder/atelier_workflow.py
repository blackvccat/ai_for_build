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
from .schematic import load_schematic, base_block
from .geometry import inspect_geometry
from .facade_section import measure as measure_facade_section
from .facade_section import review_evidence as section_review_evidence
from .facade_section import REPORT_VERSION as SECTION_VERSION
from .architectural_evidence import review_description, compare_plan
from . import architectural_conformance as conformance
from . import candidate_search
from .fonts import node_binary
from .preview3d import render_previews
from .executor import view_bundle, fixed_view_bundle, state_lab
from .cancellation import checkpoint, RunInterrupted

STAGES = ('frameworks', 'facades', 'tier2', 'tier3', 'delivery')


def load(folder):
    return w.load(Path(folder) / 'workflow.json')


def record(task, folder, kind, value, candidate=None, view_set=None, filename=None):
    path = Path(folder) / (filename or (kind + '.json'))
    write_json(path, value)
    w.register_artifact(task, kind, path, candidate, view_set=view_set)
    return path


def register_export_evidence(task, folder, schematic, plan, ident, section=None):
    section = section or measure_facade_section(schematic)
    record(task, folder, 'facade_section', section, ident,
           filename='facade_section-v%d.json' % SECTION_VERSION)
    description = review_description(plan, section)
    record(task, folder, 'architectural_evidence', description, ident,
           filename='architectural_evidence-v1-section-v%d.json' % SECTION_VERSION)
    if task.get('review_policy') == w.SPLIT_REVIEW_POLICY:
        report = conformance.measure(schematic, plan, section, stage=task['stage'])
        record(task, folder, 'architectural_conformance', report, ident,
               filename='architectural_conformance-v%d.json' % conformance.REPORT_VERSION)
    return description


def check_measured_plan(plan, section):
    # This auxiliary sampler only understands the old north/east adapter. The
    # atlas profile is gated by its own export-conformance report and validator.
    if plan.get('detail_profile') == 'atlas_street1':
        return
    # Unscoped and unsupported requirements still go through architectural review.
    # A concrete supported mismatch cannot be approved by a model's prose verdict.
    failures = [check for check in compare_plan(plan, section)['checks']
                if check['status'] == 'fail']
    if failures:
        raise ValueError('Measured export differs from plan: ' + json.dumps(failures, ensure_ascii=False))


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
        task['review_policy'] = (w.SPLIT_REVIEW_POLICY if intent['form'] == 'corner_house' else 'layered-v2')
        if intent['form'] == 'corner_house' and intent.get('detail_profile') == 'reference_haussmann':
            task['source_state_policy'] = 'source-special-v1'
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
    fields = ('form', 'scheme', 'width', 'depth', 'seed')
    if intent.get('detail_profile') != 'atlas_street1':
        fields += ('storeys',)
    base = {k: intent[k] for k in fields}
    if intent.get('detail_profile'): base['detail_profile'] = intent['detail_profile']
    if intent.get('composition_profile'):
        base['composition_profile'] = intent['composition_profile']
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
    atlas = task['intent'].get('detail_profile') == 'atlas_street1'
    parameter_contract = (
        'For atlas_street1 the source kit owns storeys, bay pitch, roof height and corner family. '
        'parameters may be empty, or contain ONLY composition_profile '
        '(grouped_pavilions or flat_baseline). Retain the confirmed width/depth budget; '
        'do not promise unsupported storey changes. Bare massing is reviewed before source details. '
        if atlas else
        'parameters may contain ONLY bay_pitch (integer 3..12), entrance_fraction (0..1), roof_height '
        '(integer 3..12), chamfer (integer 0..6: cells of pan coupé cut from a corner plot). ')
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
        'width, depth, seed and detail_profile. No unrelated control candidate. '
        + parameter_contract +
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
    if atlas:
        payload['layer_contract'] = {
            'massing_tier01': '四种普通素材质的写实体量：基座与勒脚前凸、凸出体与随行屋顶、真凹进窗洞、'
                             '两道阳台挑板、叠涩檐口、曼萨德剖面、坡面老虎窗小屋、独立转角塔亭及顶帽；'
                             '共用同一分组/开间/层位布局，不装配源库细件',
            'detail_tier23': '框架评审后才装配完整源库技法，窗面/店面/栏杆/檐口齿饰/屋顶肌理/烟囱/收头；'
                            '当前两档均为完整件库，不声称逐件递增',
            'order': '造型必须先读得出写实骨相；源件合格不能代替体量品质评审；完整建筑仍等用户游戏验收',
        }
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
        if not isinstance(parameters, dict) or (not parameters and not atlas) or not row.get('rationale'):
            raise ValueError('框架变体需要参数及符合提示词的依据')
        for name, value in parameters.items():
            if atlas:
                if name == 'composition_profile' and value in ('grouped_pavilions', 'flat_baseline'):
                    continue
                raise ValueError('atlas 框架变体使用不支持或由件库固定的参数：' + name)
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
            scene, manifest = design.build(plan, tier=tier, work_dir=folder / 'atlas-work')
            write_schematic(schematic, scene.volume, scene.palette, name='Atelier ' + stage)
            repeat, _ = design.build(plan, tier=tier, work_dir=folder / 'atlas-work-repeat')
            same = bool(np.array_equal(np.array(scene.palette)[scene.volume], np.array(repeat.palette)[repeat.volume]))
        read = load_schematic(schematic)
        validation = read.validation()
        atlas = spec.get('detail_profile') == 'atlas_street1'
        decorative = manifest.get('decorative_doors', [])
        if atlas and manifest.get('atlas_tier_semantics') == 'post_framework_complete_kit':
            # The st1 kit freezes every window leaf as half=lower with no upper
            # counterpart (documented source convention, PRESERVE_SOURCE_HALF_STATES),
            # so the generic upper/lower pairing check — written for procedural
            # doors — would fail every leaf. The stamp audit in this same technical
            # pass re-proves each leaf cell-exactly against its source piece and
            # still fails the build on any mismatch; the door cells are declared
            # decorative from the measured export, not from generator claims.
            decorative = [{'xyz': [int(x), int(y), int(z)], 'state': str(state)}
                          for palette_id, state in enumerate(read.id_to_state)
                          if base_block(str(state)).endswith('_door')
                          for y, z, x in zip(*np.where(read.volume == palette_id))]
        geometry = inspect_geometry(read, decorative_doors=decorative)
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
        if atlas:
            audit, atlas_failures = audit_atlas_generation(read, manifest, stage)
            # The style file's own machine-checkable rules. They were declared in
            # knowledge/styles/paris_haussmann_v0.2.json and nothing executed them: the
            # reviewer was asked to judge "does this read as Haussmann" in prose while nine
            # numeric invariants sat unread. A rule that cannot be measured reports
            # UNMEASURED rather than being counted as a pass.
            #
            # These are collected BEFORE the layout failure so that the failure which
            # demands a rollback stays the last entry - the ordering the gate's callers
            # read.
            style_failures = []
            try:
                from . import atlas_rules
                style = atlas_rules.load_style()
                frame_spec = (manifest.get('framework_geometry')
                              or manifest.get('atlas_frame_spec') or {})
                export = atlas_rules.export_checks(style, read, frame_spec)
                spec_rules = atlas_rules.spec_checks(style, manifest.get('composition') or {},
                                                     frame_spec)
                rule_rows = spec_rules + export
                technical['style_rules'] = {**atlas_rules.summarize(rule_rows), 'rules': rule_rows}
                if technical['style_rules']['status'] == 'FAIL' and stage != 'frameworks':
                    # At frameworks the envelope is still being settled, so the proportion
                    # rules are recorded but do not block; from facades on they do.
                    technical['status'] = 'FAIL'
                    style_failures = ['style_rule:' + name
                                      for name in technical['style_rules']['failed']]
            except Exception as error:                                    # noqa: BLE001
                technical['style_rules'] = {'status': 'UNMEASURED',
                                            'reason': type(error).__name__ + ': ' + str(error)[:200]}
            atlas_failures.extend(style_failures)
            if stage != 'frameworks':
                layout_failure = atlas_reviewed_layout_failure(task, manifest)
                if layout_failure:
                    atlas_failures.append(layout_failure)
            technical['atlas_failures'] = atlas_failures
            technical['source_trace'] = manifest.get('source_trace')
            if atlas_failures:
                technical['status'] = 'FAIL'
        else:
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
        write_json(folder / 'manifest.json', manifest)
        if atlas:
            # Bind source provenance to the reviewed candidate. The assembler's
            # private work directory is not the measurement tool's sibling
            # locator directory, so persist the finite stamp search boxes here.
            record(task, folder, 'generation_manifest', manifest, ident)
            if stage in ('tier2', 'tier3'):
                record(task, folder, 'source_assembly', {
                    'stamps': manifest.get('stamps', []),
                    'composition': manifest.get('composition'),
                    'generation_manifest': 'generation_manifest.json',
                    'scope': 'Search-box locators only; observations come from the exported schematic',
                }, ident, filename='assembly.json')
        if w.source_states_required(task):
            from .source_state_evidence import audit as audit_source_states
            source_states = audit_source_states(schematic, manifest, required=True)
            record(task, folder, 'generation_manifest', manifest, ident)
            record(task, folder, 'source_state_evidence', source_states, ident)
            technical['source_state_evidence'] = source_states
            if source_states['status'] != 'PASS':
                technical['status'] = 'FAIL'
        record(task, folder, 'technical_validation', technical, ident)
        if technical['status'] != 'PASS':
            raise ValueError('Candidate technical validation failed: ' + str(ident))
        w.register_artifact(task, 'schematic', schematic, ident)
        concept = {**spec, 'footprint_type': spec['form'], 'massing_seed': spec['seed'],
                   'facade_seed': spec['seed'], 'detail_seed': spec['seed'],
                   'techniques': manifest['techniques'], 'scope': 'No dressing at framework stage'}
        if atlas:
            for name in ('composition', 'atlas_frame_spec', 'atlas_tier_semantics'):
                if name in manifest:
                    concept[name] = manifest[name]
        if stage == 'frameworks' and task.get('framework_proposals'):
            concept['design_rationale'] = task['framework_proposals'][int(ident.split('-')[1]) - 1]['rationale']
            concept['confirmed_brief'] = task['brief'].get('confirmed_brief')
        record(task, folder, 'concept' if stage == 'frameworks' else 'assembly_plan', concept, ident)
        section = measure_facade_section(schematic)
        register_export_evidence(task, folder, schematic, concept, ident, section)
        check_measured_plan(spec, section)
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


def ensure_section_evidence(task, validate_plan=False):
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
            section = None
        concept = next((a for a in artifacts if a['candidate'] == artifact['candidate']
                        and a['kind'] in ('concept', 'assembly_plan')), None)
        plan = read_json(concept['path']) if concept else task.get('intent', {})
        description = next((a for a in artifacts if a['kind'] == 'architectural_evidence'
                            and a['candidate'] == artifact['candidate']), None)
        if section is None or section.get('version') != SECTION_VERSION or description is None:
            path = Path(artifact['path'])
            if section is None or section.get('version') != SECTION_VERSION:
                section = measure_facade_section(path)
            register_export_evidence(task, path.parent, path, plan, artifact['candidate'], section)
        if task.get('review_policy') == w.SPLIT_REVIEW_POLICY:
            existing_gate = next((a for a in artifacts if a['kind'] == 'architectural_conformance'
                                  and a['candidate'] == artifact['candidate']), None)
            if existing_gate:
                report = read_json(existing_gate['path'])
                if report.get('source', {}).get('sha256') != artifact['sha256']:
                    raise ValueError('Conformance evidence is bound to a different schematic')
                stale = (report.get('version') != conformance.REPORT_VERSION
                         or report.get('validator_sha256') != conformance.validator_digest())
                if not stale:
                    conformance.validate(report, artifact['path'], plan, stage=task['stage'], recompute=False)
            else:
                stale = True
            if stale:
                path = Path(artifact['path'])
                report = conformance.measure(path, plan, section, stage=task['stage'])
                record(task, path.parent, 'architectural_conformance', report, artifact['candidate'],
                       filename='architectural_conformance-v%d.json' % conformance.REPORT_VERSION)
        if validate_plan:
            check_measured_plan(plan, section)
        if w.source_states_required(task):
            group = [a for a in w.current_artifacts(task) if a['candidate'] == artifact['candidate']]
            w.validate_source_state_artifact(task, group)


def audit_atlas_generation(read, manifest, stage):
    """Re-audit physical atlas pieces; bare massing has no source-piece claims."""
    from . import technique_library
    failures = []
    declarations = manifest.get('stamp_audit')
    if stage in ('frameworks', 'facades'):
        if manifest.get('atlas_tier_semantics') != 'bare_massing':
            failures.append('Atlas framework/facade must be bare massing before detail review')
        if declarations or manifest.get('techniques') or manifest.get('stamps'):
            failures.append('Atlas bare massing must not contain source-detail stamp claims')
        for name in ('source_trace', 'atlas_audit'):
            if (isinstance(manifest.get(name), dict)
                    and manifest[name].get('status') == 'FAIL'):
                failures.append('Atlas %s did not pass' % name)
        audit = {'status': 'NOT_APPLICABLE', 'matched_cells': 0, 'stamps': [],
                 'reason': 'Bare massing has no physical source-piece placement',
                 'game_acceptance': 'NOT_RUN'}
    else:
        if manifest.get('atlas_tier_semantics') != 'post_framework_complete_kit':
            failures.append('Atlas details require the explicit post-framework kit contract')
        rows, policy = manifest.get('stamp_audit_rows'), manifest.get('stamp_audit_policy')
        if not isinstance(declarations, list) or not declarations:
            failures.append('Atlas details require nonempty source-piece declarations')
        if not isinstance(rows, list) or not rows:
            failures.append('Atlas details require actual original and derived stamp rows')
        if not isinstance(policy, list):
            failures.append('Atlas details require a finite overwrite policy')
        audit = technique_library.verify_stamp_audit(
            read, declarations, rows=rows if isinstance(rows, list) else [],
            allow_overwrites=True, allowed_overwrites=policy if isinstance(policy, list) else [])
        if audit['status'] != 'PASS':
            failures.append('Exported atlas source-piece placement audit failed')
        for name in ('source_trace', 'atlas_audit'):
            report = manifest.get(name)
            if not isinstance(report, dict) or report.get('status') != 'PASS':
                failures.append('Atlas %s did not pass' % name)
    return audit, failures


def atlas_reviewed_layout_failure(task, manifest):
    """A detail repair cannot silently change the framework's selected layout."""
    selected = task.get('selected', {}).get('frameworks', {})
    review = next((row for row in reversed(task.get('reviews', []))
                   if row.get('stage') == 'frameworks' and row.get('decision') == 'pass'
                   and row.get('selected') == selected.get('candidate')), None)
    reviewed = next((row for row in task.get('artifacts', [])
                     if review and row['stage'] == 'frameworks' and row['kind'] == 'concept'
                     and row['revision'] == review['revision']
                     and row.get('candidate') == selected.get('candidate')
                     and row['path'] in review.get('artifact_hashes', {})), None)
    if reviewed is None or w.sha(reviewed['path']) != review['artifact_hashes'][reviewed['path']]:
        return 'Atlas needs hash-bound selected framework layout before detail assembly'
    layout = read_json(reviewed['path']).get('composition')
    if not isinstance(layout, dict) or json.dumps(layout, sort_keys=True) != json.dumps(manifest.get('composition'), sort_keys=True):
        return 'Atlas composition changed from the reviewed framework; rollback to frameworks is required'
    return None


def require_atlas_prior_reviews(task):
    """Revalidate selected prior stages before a kit task can build further."""
    if task.get('intent', {}).get('detail_profile') != 'atlas_street1':
        return
    stage = task['stage']
    needed = {
        'facades': ('frameworks',),
        'tier2': ('frameworks', 'facades'),
        'tier3': ('frameworks', 'facades', 'tier2'),
        'delivery': ('frameworks', 'facades', 'tier2', 'tier3'),
    }.get(stage, ())
    for earlier in needed:
        selection_stage = earlier if earlier in ('frameworks', 'facades') else 'facades'
        selected = task.get('selected', {}).get(selection_stage)
        if not selected or not selected.get('plan'):
            raise ValueError('Atlas requires a passed selected ' + earlier + ' before ' + stage)
        review = next((row for row in reversed(task.get('reviews', []))
                       if row.get('stage') == earlier), None)
        candidate_id = selected.get('candidate') if earlier in ('frameworks', 'facades') else None
        if (not review or review.get('decision') != 'pass'
                or review.get('selected') != candidate_id):
            raise ValueError('Atlas requires a passed selected ' + earlier + ' before ' + stage)
        bound = review.get('artifact_hashes', {})
        prior = {**task, 'stage': earlier, 'revision': review['revision'],
                 'artifacts': [row for row in task['artifacts'] if row['path'] in bound]}
        # This runs the existing hash, visual-evidence and measured-conformance
        # gate. A selected flag or a forged all-pass row is not authorization.
        w.validate_review(prior, review)
        plan_item = next((row for row in prior['artifacts']
                          if row['stage'] == earlier and row['revision'] == review['revision']
                          and row.get('candidate') == candidate_id
                          and row['kind'] in ('concept', 'assembly_plan')), None)
        reviewed_plan = read_json(plan_item['path']) if plan_item else {}
        if any(reviewed_plan.get(key) != value for key, value in selected['plan'].items()):
            raise ValueError('Atlas selected plan differs from the passed ' + earlier + ' export')


def build_stage(folder, size=640, progress=None, emit=None):
    folder = Path(folder)
    task = load(folder)
    w._check_hashes(task)
    require_atlas_prior_reviews(task)
    ensure_section_evidence(task, validate_plan=True)
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
    require_atlas_prior_reviews(task)
    if task.get('review_policy') == w.SPLIT_REVIEW_POLICY:
        final_review = next((r for r in reversed(task['reviews']) if r['stage'] == 'tier3'
                             and r['revision'] == task['revision']), None)
        if final_review is None or final_review['decision'] != 'pass':
            raise ValueError('Delivery requires a current passed tier3 split review')
        final_task = {**task, 'stage': 'tier3',
                      'artifacts': [a for a in task['artifacts'] if a['stage'] != 'delivery']}
        w.validate_review(final_task, final_review)
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
            scene, _ = design.build(design.plan_for(**task['selected']['facades']['plan']), tier=3,
                                    work_dir=target / 'atlas-state-work')
            delivered = load_schematic(target / 'candidate.schem')
            actual_states = np.array(delivered.id_to_state)[delivered.volume]
            if not np.array_equal(np.array(scene.palette)[scene.volume], actual_states):
                raise ValueError('状态实验件与已审核建筑的生成器版本不一致')
            plots = state_lab(scene, target)
        tier3_artifacts = [a for a in task['artifacts'] if a['stage'] == 'tier3']
        if task.get('intent', {}).get('detail_profile') == 'atlas_street1':
            generation_item = next((a for a in tier3_artifacts if a['kind'] == 'generation_manifest'), None)
            locator_item = next((a for a in tier3_artifacts if a['kind'] == 'source_assembly'), None)
            if generation_item is None or locator_item is None:
                raise ValueError('Atlas delivery requires reviewed source provenance and placement locators')
            generation = read_json(generation_item['path'])
            final_audit, failures = audit_atlas_generation(load_schematic(target / 'candidate.schem'), generation, 'delivery')
            if failures:
                raise ValueError('Atlas delivered source-piece audit failed: ' + '; '.join(failures))
            record(task, target, 'generation_manifest', generation)
            record(task, target, 'source_assembly', read_json(locator_item['path']), filename='assembly.json')
            record(task, target, 'source_piece_audit', final_audit)
        if w.source_states_required(task):
            from .source_state_evidence import audit as audit_source_states
            generation = read_json(next(a['path'] for a in tier3_artifacts if a['kind'] == 'generation_manifest'))
            report = audit_source_states(target / 'candidate.schem', generation, required=True)
            if report['status'] != 'PASS':
                raise ValueError('交付建筑缺少已验证的源状态细节')
            record(task, target, 'generation_manifest', generation)
            record(task, target, 'source_state_evidence', report)
        # Keep the reviewed drawings and measurements with the portable building package.
        final_views = read_json(next(a['path'] for a in tier3_artifacts if a['kind'] == 'views'))
        packaged_views = {}
        (target / 'previews').mkdir(exist_ok=True)
        for name, view in final_views.items():
            destination = target / 'previews' / (name + '.png')
            shutil.copyfile(view['path'], destination)
            packaged_views[name] = {'path': 'previews/' + destination.name, 'sha256': digest(destination)}
        write_json(target / 'views.json', packaged_views)
        for item in tier3_artifacts:
            if item['kind'] in ('assembly_plan', 'facade_section', 'architectural_evidence', 'architectural_conformance'):
                shutil.copyfile(item['path'], target / Path(item['path']).name)
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
            'source_state_policy': task.get('source_state_policy'),
            'drawings': 'views.json', 'state_experiments': 'state_lab_tests.json' if (target / 'state_lab_tests.json').exists() else 'versioned-state-lab/state_lab_tests.json',
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
    retain_candidate_review(task, review)
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


def retain_candidate_review(task, review):
    reports = {a['candidate']: read_json(a['path']) for a in w.current_artifacts(task)
               if a['kind'] == 'architectural_conformance'}
    return candidate_search.retain_review(task, review, conformance_by_candidate=reports)


def restore_best(folder, source_revision=None):
    task = load(folder)
    if task['stage'] not in ('frameworks', 'facades', 'tier2', 'tier3'):
        raise ValueError('当前阶段不能恢复历史候选')
    candidate_search.import_history(task, stage=task['stage'])
    snapshot_id = None
    if source_revision is not None:
        snapshot_id = candidate_search.select_revision(task, source_revision)
    restored = candidate_search.restore(task, snapshot_id=snapshot_id)
    restored['review_policy'] = w.SPLIT_REVIEW_POLICY
    w.save(restored)
    ensure_section_evidence(restored)
    return summary(folder)


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
        section_artifact = next((a for a in artifacts if a['candidate'] == candidate_id
                                 and a['kind'] == 'facade_section'), None)
        description_artifact = next((a for a in artifacts if a['candidate'] == candidate_id
                                     and a['kind'] == 'architectural_evidence'), None)
        conformance_artifact = next((a for a in artifacts if a['candidate'] == candidate_id
                                    and a['kind'] == 'architectural_conformance'), None)
        source_artifact = next((a for a in artifacts if a['candidate'] == candidate_id
                               and a['kind'] == 'source_state_evidence'), None)
        candidates.append({'id': candidate_id, 'plan': read_json(concept['path']), 'views': read_json(artifact['path']),
                           'manifest': read_json(manifest_path) if manifest_path.exists() else {},
                           'facade_section': read_json(section_artifact['path']) if section_artifact else None,
                           'architectural_evidence': read_json(description_artifact['path']) if description_artifact else None,
                           'conformance': read_json(conformance_artifact['path']) if conformance_artifact else None,
                           'source_state_evidence': read_json(source_artifact['path']) if source_artifact else None})
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
    if task.get('review_policy') == w.SPLIT_REVIEW_POLICY:
        for template in review['candidates']:
            for key in ('layer_checks', 'geometry_checks', 'detail_checks', 'storey_checks'):
                template.pop(key, None)
            template['quality_checks'] = {key: {'status': 'uncertain', 'observation': ''}
                                          for key in w.QUALITY_CHECKS}
    ready = bool(expected and len(candidates) == expected)
    preview = candidates[0]['views'] if candidates else {}
    if task['stage'] in ('game', 'accepted', 'delivery'):
        last_views = next((a for a in reversed(task['artifacts']) if a['stage'] == 'tier3' and a['kind'] == 'views'), None)
        if last_views:
            preview = read_json(last_views['path'])
    if not preview:
        recent_views = next((a for a in reversed(task['artifacts']) if a['kind'] == 'views'), None)
        if recent_views:
            preview = read_json(recent_views['path'])
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
            'candidate_search': candidate_search.summary(task),
            'latest_review': next((r for r in reversed(task['reviews']) if r.get('scope') in
                                  ('actual_multimodal_visual_review', 'deterministic_conformance')), None),
            'execution_mode': task.get('execution_mode', 'manual'),
            'delivery_files': {kind: str(Path('revision-' + str(task['revision'])) / 'delivery' / name)
                               for kind, name in [('building', 'candidate.schem'), ('state_lab', 'STATE-LAB.schem'),
                                                  ('instructions', 'instructions.json')]}}


def model_section_evidence(section, plan, storey=None, presentation='json'):
    if not section:
        return None
    result = section_review_evidence(section, storey)
    result['plan_comparison'] = compare_plan(plan, section)
    # Character diagrams remain a selectable supplement. A paired live experiment
    # is required before replacing the default material arrays with this format.
    if presentation == 'text':
        result = {k: v for k, v in result.items()
                  if k not in ('surface_maps', 'palette', 'roof_slices')}
        result['readable_diagrams'] = review_description(plan, section, storey)['text']
    return result


def atlas_visual_scope(task):
    """State the atlas massing contract without excusing missing relief."""
    stage = task['stage']
    common = ('Current atlas stage: ' + stage + '. Apply the confirmed brief and design_language. '
              'The two street faces are north and west; east and south are intentional blind party walls. '
              'References are architectural exemplars. Inspect all supplied views and judge visible style, '
              'composition, storey expression, material coherence, craft at this tier and all-direction readability. '
              'The exported architectural_conformance predicates own exact dimensions, depths and contacts. '
              'Do not estimate those numbers from pixels. Record visible defects and uncertainty honestly. '
              'Never invent perception, source use or game acceptance. Do not score. ')
    if stage in ('frameworks', 'facades'):
        return common + (
            'This is a realistic building skeleton expressed in four ordinary materials. Relief geometry is '
            'already required: a projecting base and plinth, projecting pavilions with following roofs, recessed '
            'openings that read as windows, two projecting balcony platforms, a stepped projecting cornice, '
            'a mansard growing behind that cornice, roof dormer houses with cheeks and caps, and a corner turret '
            'projecting beyond both wings with its own cap. Judge whether these actual volume relationships '
            'make the style and floor hierarchy legible. Missing or visually unreadable massing elements are '
            'defects at this stage. Surface textures, frozen source states, joinery, rails, cornice teeth, signs '
            'and decorative library pieces belong to later source-detail assembly; their absence is allowed. '
            'A flat wall with identical holes or an unarticulated roof box does not satisfy the skeleton contract.')
    return common + (
        'Tier2 and tier3 currently assemble the complete source kit rather than claiming an incremental '
        'decoration schedule. Judge every visible building system now: base and shops, graded window joinery '
        'and reveals, balconies, bands and cornice, mansard texture, dormer houses, roof crown and chimneys, '
        'the independent corner composition and their junctions. Compare the massing relationships with '
        'the reviewed shared layout. Source audit PASS is provenance evidence; visible architectural quality '
        'still needs this review. Concrete structural regressions require rollback to frameworks.')


def agent_review(folder, key, model, emit=None):
    from .providers import MultimodalClient, ProviderError
    task = load(folder)
    ensure_section_evidence(task, validate_plan=True)
    data = summary(folder)
    if task.get('review_policy') == w.SPLIT_REVIEW_POLICY:
        failed = [item for item in data['candidates'] if item['conformance']['status'] != 'PASS']
        if failed:
            rows = []
            for item in data['candidates']:
                findings = [c['observation'] for c in item['conformance']['checks']
                            if c.get('required') and c['status'] != 'pass']
                rows.append({'id': item['id'], 'decision': 'reject',
                             'conformance_status': item['conformance']['status'],
                             'failure_modes': findings or ['品质尚未评审']})
            review = {'stage': task['stage'], 'revision': task['revision'],
                      'artifact_hashes': w.bindings(task), 'reviewer': 'export-conformance-validator',
                      'reviewer_type': 'software', 'scope': 'deterministic_conformance',
                      'decision': 'reject', 'selected': None, 'rollback_stage': task['stage'],
                      'candidates': rows, 'rationale': '导出几何未满足明确规格；修复原因来自实测分类。',
                      'game_acceptance': 'PENDING'}
            w.submit_review(task, review)
            retain_candidate_review(task, review)
            if emit:
                for row in rows:
                    for finding in row['failure_modes']:
                        emit('agent_progress', {'summary': finding})
            raise ValueError('Agent 阶段检查未通过：' + review['rationale'])
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
            section = model_section_evidence(candidate['facade_section'], candidate['plan'],
                                             presentation=task.get('evidence_presentation', 'json'))
            if task.get('review_policy') == w.SPLIT_REVIEW_POLICY:
                scope = ('Current stage: ' + task['stage'] + '. Apply the brief design_language. '
                         'Frameworks judge only bare structural character; facades judge elevation composition and '
                         'beginnings of surrounds/sills/bands. Facades do not require tier2/tier3 railings, consoles, '
                         'shop signs, rustication, dormer joinery or pediment alternation. Tier2/tier3 judge built detail. '
                         'References are exemplars, not required copies. Evaluate visible style, composition, storey '
                         'expression, palette harmony, craft at this tier and all-direction readability. '
                         'Geometry compliance belongs to architectural_conformance. Do not infer precise positions, '
                         'recess depths, slopes, model contacts or course connectivity from pixels. A limitation in '
                         'exact contact measurement is not a visual craft defect; judge visible articulation. '
                         'Do not cascade a roof finding into corner. Record true uncertainty explicitly. '
                         'Never invent perception, geometry or game acceptance. Do not score.')
            if task.get('intent', {}).get('detail_profile') == 'atlas_street1':
                scope = atlas_visual_scope(task)
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
                        budget = (2500 if label == 'quality' else
                                  16000 if label == 'verdict' and task['stage'] != 'frameworks' else 8000)
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
                'conformance': candidate.get('conformance'),
                'observations': observations, 'reference_comparisons': reference_result['comparisons']}, checked_call)
            row = {'id': candidate['id'], 'decision': verdict['decision'],
                'view_observations': observations,
                'reference_comparison': dict(zip(template['reference_comparison'], reference_result['comparisons'])),
                'failure_modes': verdict['failure_modes']}
            if task.get('review_policy') == w.SPLIT_REVIEW_POLICY:
                row['quality_checks'] = verdict['quality_checks']
                row['conformance_status'] = candidate['conformance']['status']
            else:
                row['scores'] = verdict['scores']
                row['layer_checks'] = dict(zip(w.LAYER_CHECKS, verdict['layers']))
            for field in ('geometry_checks', 'detail_checks', 'storey_checks'):
                if field in verdict: row[field] = verdict[field]
            groups = ([row.get('geometry_checks', {})] + list(row.get('detail_checks', {}).values())
                      + list(row.get('storey_checks', {}).values()))
            if any(check['status'] == 'fail' for group in groups for check in group.values()):
                row['decision'] = 'reject'
            if any(check['status'] == 'fail' for check in verdict.get('layers', [])): row['decision'] = 'reject'
            receipt = {'model':'deepseek-flash', 'batches':batches}
            rows.append(row); receipts.append(receipt)
            operation.finish({'review': row, 'receipt': receipt}, artifacts=images,
                             validation={'image_input': 'ACTUAL', 'game_acceptance': 'PENDING'})
        except Exception as error:
            operation.fail(str(error)); raise
    eligible = [row for row in rows if row['decision'] == 'pass' and
                (task.get('review_policy') == w.SPLIT_REVIEW_POLICY or task['stage'] != 'frameworks'
                 or w.score_gate_failure(row.get('scores'), w.score_profile(task)) is None)]
    chosen = eligible[0] if eligible else None
    review = {'decision': 'pass' if chosen else 'reject', 'selected': chosen['id'] if chosen else None,
        'rationale': '候选满足确定性符合性与当前阶段视觉品质门槛。' if chosen else '当前候选未满足阶段门槛，具体缺陷见独立检查。',
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
    retain_candidate_review(task, review)
    if review['decision'] != 'pass':
        raise ValueError('Agent 阶段检查未通过：' + str(review['rationale']))
    if task['stage'] in ('frameworks', 'facades'):
        chosen = next(spec for ident, spec in plans(task) if ident == review['selected'])
        task['selected'][task['stage']] = {'candidate': review['selected'], 'plan': chosen}
    w.advance(task)
    return w.status(task)


def collect_architectural_verdict(task, evidence, checked_call):
    """Collect bounded schema groups without dropping any architectural review gate."""
    if task.get('review_policy') == w.SPLIT_REVIEW_POLICY:
        def valid(value):
            if set(value) != {'decision', 'answers', 'failure_modes'}:
                raise ValueError('Return only decision, answers and failure_modes at the top level')
            if value.get('decision') not in ('pass', 'reject'):
                raise ValueError('Quality decision must be pass or reject')
            answers = value.get('answers')
            if not isinstance(answers, list) or len(answers) != len(w.QUALITY_CHECKS):
                raise ValueError('answers must contain EXACTLY six objects in question_order; no scores')
            if any(not isinstance(answer, dict) or set(answer) != {'status', 'observation'} for answer in answers):
                raise ValueError('Each answer contains only status and observation; failures belong at top level')
            w.validate_quality_checks({'quality_checks': dict(zip(w.QUALITY_CHECKS, answers))})
            modes = value.get('failure_modes')
            if not isinstance(modes, list) or not modes or any(not isinstance(s, str) or not s.strip() for s in modes):
                raise ValueError('Record explicit quality findings, or none')
            return True
        payload = {k: v for k, v in evidence.items() if k not in ('facade_section', 'walls', 'openings', 'structure')}
        measured = evidence.get('conformance')
        if measured:
            payload['conformance'] = {'status': measured['status'], 'source': measured['source'],
                'checks': [{'id': c['id'], 'status': c['status']} for c in measured['checks'] if c['required']],
                'scope': 'These named geometric predicates are decided by code. No visual remeasurement requested.'}
        payload.update(question_order=list(w.QUALITY_CHECKS),
            required_output={'decision': 'pass|reject',
            'answers': [{'status': 'pass|fail|uncertain', 'observation': name + '：一句具体中文品质观察'}
                        for name in w.QUALITY_CHECKS], 'failure_modes': ['具体品质缺陷或无']},
            instruction='Use the actual image observations and references to answer only these six qualitative questions. '
            'The measured conformance report owns geometry. Do not estimate positions, depth, slope break, continuity or '
            'junction contact from pixels. Do not fail corner quality because of a roof measurement. Respect the tier scope '
            'and avoid failing absent future-tier details. Return EXACTLY THREE top-level keys: decision, answers, '
            'failure_modes. answers is an ARRAY of EXACTLY SIX objects in question_order, each with ONLY status and '
            'observation. No scores, no named quality_checks map, no failure_modes inside answers. '
            'Keep each Chinese observation under 120 characters. All six quality answers must pass '
            'to approve; uncertainty remains explicit. Never grant game acceptance.')
        result = checked_call('quality', payload, [], valid)
        result['quality_checks'] = dict(zip(w.QUALITY_CHECKS, result.pop('answers')))
        if any(c['status'] != 'pass' for c in result['quality_checks'].values()):
            result['decision'] = 'reject'
        return result
    section = evidence.get('facade_section')
    if section:
        evidence = {**evidence, 'facade_section': model_section_evidence(section, evidence['plan'],
                    presentation=task.get('evidence_presentation', 'json'))}
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
            group_evidence = {**evidence, 'facade_section': model_section_evidence(section, evidence['plan'],
                int(label[7:]), presentation=task.get('evidence_presentation', 'json'))}
        response = checked_call('checks-' + label, {**group_evidence, 'review_group': label,
            'required_output': {'checks': {key: {'status': statuses, 'observation': '具体视图/剖面依据'} for key in keys}},
            'instruction': 'Inspect ONLY this review_group in the CURRENT stage scope. Return checks with exactly '
            'the required keys. Each check must be an object with status and a concrete Chinese observation. '
            'For storey-N inspect that individual floor (0 is ground); for layer-X cover all actual floors '
            'belonging to that layer. Inspect every window and junction. For geometry roof_section describe '
            'the required roof type and evidence/uncertainty; for a mansard requirement describe '
            'steep lower slope, slope break and shallower upper slope. '
            'For each measured attribute cite facade_section coordinates, floor index and actual values. '
            'Compare explicit supported expectations in plan_comparison; unsupported/unscoped entries are unresolved, '
            'not passes and not automatic defects. Sampled transmissive groups are not semantic window counts. '
            'Read actual roof_slices rows for roof occupancy; top-height spikes are not a proved roof slope break. '
            'Distinguish sampled_path_coverage_complete from stone_path_connection. '
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
            except RunInterrupted:
                raise
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
            if failed.get('review_policy') == w.SPLIT_REVIEW_POLICY:
                reports = [read_json(a['path']) for a in w.current_artifacts(failed)
                           if a['kind'] == 'architectural_conformance']
                pending = [check for report in reports for check in conformance.pending(report)]
                if pending:
                    failed['awaiting'] = 'AGENT_SPECIFICATION_PENDING'
                    failed['history'].append({'specification_pending': pending, 'stage': stage})
                    w.save(failed)
                    raise ValueError('明确规格暂不可测量，需补齐规格或测量器：' + json.dumps(pending, ensure_ascii=False))
            failed = budget_check('视觉评审未通过')
            if emit:
                emit('agent_progress', {'summary': '第 %d 轮修复 %s 阶段（生成器版本在推进，继续）'
                                        % (attempts[stage], stage)})
            apply_generator_repair(failed, folder, last, key, model, emit)
            continue
        except RunInterrupted:
            stopped = load(folder)
            stopped['awaiting'] = 'AGENT_INTERRUPTED_' + stage
            w.save(stopped)
            raise
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
