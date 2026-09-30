"""Intent routing, reality-backed research delegation, and DSH design."""
import json
from pathlib import Path
from uuid import uuid4

from .harness_runtime import run_json
from . import house, facade, technique


ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT / 'runs' / 'LEARNING-WORKBENCH-v1' / 'dsh-home'
PATCH_TEMPLATE = ROOT / 'agent' / 'building.patch.yml'
TOOLS = ROOT / 'agent' / 'building-tools.mjs'
REALITY = ROOT / 'knowledge/styles/paris_haussmann_v0.1.json'


def evidence_ids(value):
    """Normalize the two equivalent citation shapes, never invent/repair IDs."""
    if isinstance(value, dict):
        if not set(value) <= {'structure', 'facade', 'technique', 'component'}:
            raise ValueError('引用分层名称不合法')
        if not all(isinstance(group, list) for group in value.values()):
            raise ValueError('各层引用必须是ID数组')
        value = [ident for group in value.values() for ident in group]
    if not isinstance(value, list) or not value or not all(isinstance(i, str) and i for i in value):
        raise ValueError('方案缺少有效的引用ID数组')
    return list(dict.fromkeys(value))


def classify_turn(key: str, text: str, history: list[dict], model: str, *, emit=None, parent=None, reference_analysis=None) -> dict:
    prompt = json.dumps({'history': history[-24:], 'current_input': text, 'reference_image_analysis': reference_analysis,
        'instruction': ('Resolve the CURRENT input against conversation history, including short confirmations '
                        'such as 请开始, 可以开始了 or 理解的话就开始. Execute the most recent unfinished user task. '
                        'Return JSON action=reply|draft|design|revise and reply=Chinese response for reply/draft. '
                        'Greetings, capability questions and '
                        'non-actionable comments are reply even when history contains design requests. '
                        'Requests to write, improve, or discuss a prompt, brief, or plan BEFORE starting '
                        'are draft: provide the COMPLETE requested prompt/brief/plan in reply NOW, '
                        'including the user constraints, style, massing, roof, layered facade details and review gates. '
                        'Framework review must settle architectural form, massing, proportions and roof section '
                        'BEFORE refinement. For a mansard roof specify the steep lower slope, shallower upper slope, '
                        'slope break, ridge and corner/wing junctions, with uncertain reference features labeled. '
                        'Refinement review must inspect EACH storey and its windows, reveals, lintels, sills, '
                        'balconies, railings, cornices, ornaments and material junctions, including dormers and chimneys. '
                        'These are agent review responsibilities. Propose justified defaults for routine missing '
                        'parameters; only ask user decisions needed to resolve material ambiguity. '
                        'A promise to write later or acknowledgement alone does not complete the task. '
                        'If 请开始 follows a request to draft a prompt, finish that draft; '
                        'if it follows approval to build, choose design/revise. '
                        'When reference_image_analysis is present, the uploaded images HAVE been received and actually '
                        'inspected by a vision model. Use the supplied pixel observations; never ask the user to re-upload '
                        'those same images or falsely claim no image was received. Do not invent unseen details. '
                        'Reference notes written by the user are part of the task brief: if a note asks for a '
                        'complete prompt before construction, deliver that prompt using the image observations. '
                        'The application is a Minecraft 1.21.11 architectural workbench; distinguish architectural '
                        'requirements from feasible block techniques and do not substitute a photography prompt. '
                        'Choose design or revise only for an explicit request to create, execute, or change '
                        'a building. Do not research or design in this classification step.')},
        ensure_ascii=False)
    result, _receipt = run_json(key, model, prompt, phase='intent', max_tokens=6000, emit=emit, parent=parent)
    def unfinished_draft(value):
        reply = value.get('reply', '')
        if not isinstance(reply, str): return False
        pending = any('提示词' in row.get('content', '') for row in history if row.get('role') == 'user')
        confirmation = text.strip(' 。！!').lower() in ('请开始', '开始', '可以开始了', '开始吧', 'ok')
        explicit = '提示词' in text and any(word in text for word in ('生成', '写', '完善', '细化'))
        return (value.get('action') == 'draft' or (pending and confirmation) or explicit) and \
               value.get('action') in ('reply', 'draft') and len(reply.strip()) < 200
    if unfinished_draft(result):
        retry = json.loads(prompt)
        retry['completion_error'] = 'Previous response did not deliver the requested draft. Return action=draft with the full text now.'
        result, _receipt = run_json(key, model, json.dumps(retry, ensure_ascii=False),
                                   phase='intent', max_tokens=8000, emit=emit, parent=parent)
        if unfinished_draft(result):
            raise ValueError('提示词任务未完成：需要完整正文，不能只确认或承诺稍后整理')
    if result.get('action') not in ('reply', 'draft', 'design', 'revise'):
        raise ValueError('No safe intent action')
    if result['action'] in ('reply', 'draft') and not isinstance(result.get('reply'), str):
        raise ValueError('No conversational reply')
    if result['action'] == 'draft' and len(result['reply'].strip()) < 200:
        raise ValueError('提示词任务未完成：需要完整正文，不能只确认或承诺稍后整理')
    return result


def plan_turn(key: str, text: str, history: list[dict], evidence: list[dict], model: str,
              reference_notes: list[dict] | None = None, *, emit=None, parent=None) -> tuple[dict, list[str]]:
    HOME.mkdir(parents=True, exist_ok=True)
    reality = json.loads(REALITY.read_text(encoding='utf-8'))
    sources = reality['external_sources']
    source_facts = [{'id': source['id'], 'publisher': source['publisher'], 'url': source['url'],
                     'observations': source['observations']} for source in sources]
    local_facts = [{'id': row['id'], 'layer': row['layer'], 'title': row['title'],
                    'summary': row['summary'][:300], 'constraints': row.get('constraints', []),
                    'source_detail': row.get('source_detail', {}),
                    'evidence': row.get('evidence', [])} for row in evidence]
    context = {'reality': source_facts, 'knowledge': local_facts,
               'catalogue': {'forms': sorted(house.FORMS), 'schemes': sorted(facade.SCHEMES),
                             'techniques': sorted(technique.TECHNIQUES),
                             'structure_capabilities': ['mansard roof', 'glazed dormers', 'chimneys',
                                 'blind side party walls for street_house', 'street_house rear windows and door'],
                             'detail_profiles': {'reference_haussmann': {
                                 'form': 'street_house', 'min_width': 23, 'min_depth': 24,
                                 'capabilities': ['source v3 thin iron-door windows preserving half',
                                     'selected-floor continuous balconies with returns and brackets',
                                     'independent cafe and residential doors, foyer and rear door',
                                     'six storeys means six floors plus hollow mansard attic',
                                     'two-wide stairs through floor openings to attic',
                                     'two apartment room shells per floor around common circulation',
                                     'aligned glazed dormers, party-wall chimneys, rear rain leaders'],
                                 'limits': ['basic furniture only; kitchens and bathrooms not fitted',
                                            'rear court outside export; game behavior not validated']}},
                             'limits': {'width': [8, 64], 'depth': [12, 48], 'storeys': [3, 8]}}}
    notes = reference_notes or []
    research_prompt = json.dumps({'role': 'architectural_research_subagent', 'input': text, 'history': history,
        'operator_references': notes,
        'instruction': ('First call real_architecture_sources and source_evidence. Return compact JSON with '
                        'summary, source_ids (at least three supplied external source IDs), '
                        'knowledge_ids (supplied project IDs covering structure, facade, technique and component), '
                        'design_inferences, boundaries and 3-5 design_rules (all arrays of strings). Analyze the '
                        'building intent and party-wall context. Operator references include actual vision observations '
                        'when visual_observation is present; use these with their stated uncertainty. '
                        'For references without that field use only notes. Distinguish real-world rules from '
                        'Minecraft techniques. Do not invent sources or game validation.')}, ensure_ascii=False)
    research, research_receipt = run_json(key, model, research_prompt, phase='research', context=context,
        required_tools=('real_architecture_sources', 'source_evidence'), emit=emit, parent=parent)
    allowed_sources = {s['id'] for s in source_facts}
    allowed_knowledge = {r['id'] for r in local_facts}
    if (not isinstance(research.get('source_ids'), list)
            or len(set(research['source_ids'])) < 3
            or any(value not in allowed_sources for value in research['source_ids'])
            or not isinstance(research.get('knowledge_ids'), list)
            or not research['knowledge_ids']
            or any(value not in allowed_knowledge for value in research['knowledge_ids'])
            or not research.get('design_inferences') or not research.get('boundaries')):
        raise ValueError('Research subagent did not cite available reality and project sources')
    used_sources = [source for source in source_facts if source['id'] in research['source_ids']]
    summary = {'summary': research.get('summary', ''),
               'design_rules': research.get('design_rules', [])[:5],
               'real_sources': used_sources,
               'project_knowledge': [r for r in local_facts if r['id'] in research['knowledge_ids']]}
    prompt = json.dumps({'input': text, 'history': history, 'research': summary,
        'catalogue': {'forms': ['street_house', 'street_row', 'apartment_block', 'court_palace',
                                'civic_hall', 'slope_terrace'],
                      'schemes': ['haussmann_apartment', 'palace_front', 'civic_colonnade',
                                  'plain_terrace', 'shop_terrace'],
                      'techniques': ['rustication', 'quoins', 'pilaster', 'window_surround',
                                     'string_course', 'cornice', 'guard_rail', 'shopfront',
                                     'cresting', 'door_leaf'],
                      'structure_capabilities': ['mansard roof', 'glazed dormers', 'chimneys',
                                                 'party-wall parapets', 'rear windows and door']},
        'instruction': ('First call architecture_catalog, source_evidence and real_architecture_sources. '
                        'Return only compact JSON: summary, evidence_ids from project_knowledge covering all four layers, '
                        'design_spec with form, scheme and integer width/depth/storeys, optional detail_profile '
                        '(reference_haussmann from architecture_catalog for a source-derived single street_house >=23w >=24d), '
                        '(limits 8..64, 12..48, 3..8), 3-5 facade_decisions objects with '
                        'technique, placement, reason, source, unsupported_decisions array and validation_notes array. '
                        'Technique must be in catalogue.techniques. Source must exactly match a '
                        'project_knowledge ID or real source ID. '
                        'Also return architectural_contract: style (requested building type/style), invariants '
                        '(source-backed architectural rules), variation_axes (allowed independent design choices), '
                        'relationships (massing, circulation, structure/envelope and component relationships), '
                        'uncertainties (occlusion or insufficient evidence). The design language is general architecture: '
                        'Paris is one evidence domain, never a universal template. Produce distinct coherent designs '
                        'within rules, not reference-coordinate copies. Declare catalogue limitations honestly. '
                        'Roof, dormers, chimneys, party-wall '
                        'parapets and rear openings are already supported. Shared party walls stay blind. '
                        'unsupported_decisions ONLY lists specific explicitly requested construction that the catalogue cannot build. '
                        'Pending reviews, game tests, orientation checks and source uncertainty belong in validation_notes, never unsupported_decisions. '
                        'Do not invent additional required interiors, stairs or courtyards absent from the current user request. '
                        'Component crops are design references, not promised exact placements. '
                        'evidence_ids MUST be a flat JSON array of strings, not an object keyed by layer. '
                        'When reference_haussmann is selected, use its actual extended capabilities and limits from architecture_catalog. '
                        'Use Chinese for summary, reasons and limitations. Never claim visual or game acceptance.')}, ensure_ascii=False)
    for attempt in range(2):
        try:
            plan, receipt = run_json(key, model, prompt + '\nKeep final JSON concise: summary <=150 Chinese characters, '
                '3-5 decisions each <=100 characters. Do not repeat source inventories.',
                phase='design', context=context, max_tokens=12000 if attempt == 0 else 18000,
                required_tools=('architecture_catalog', 'source_evidence', 'real_architecture_sources'),
                emit=emit, parent=research_receipt['operation_id'])
            break
        except ValueError as error:
            if attempt or 'max-tokens' not in str(error): raise
            if emit: emit('agent_progress', {'summary': '设计输出被长度限制截断，正在自动重试一次；已完成的来源研究保留。'})
    plan['research_sources'] = used_sources
    plan['research_images'] = notes
    plan['research_summary'] = research.get('summary', '')
    plan['research_evidence'] = {'sources': used_sources, 'design_inferences': research['design_inferences'],
                                 'boundaries': research['boundaries']}
    plan['runtime_receipts'] = [research_receipt, receipt]
    return plan, sorted(set(research_receipt['tools'] + receipt['tools']))
