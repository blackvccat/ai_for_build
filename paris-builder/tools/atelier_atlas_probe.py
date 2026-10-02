"""离线端到端探针：atlas_street1 档在 atelier 阶段机的接线验证。

走真实链路：atelier_workflow.create（研究/检索门禁）→ build_stage（frameworks 裸框架
→ facades 同造型复核 → tier2 件库装配）→ 每阶段提交脚本化离线评审过门禁。

不调真实 LLM：评审文本是明确标注 scope='offline_mechanism_probe' 的脚本记录，
证明的是阶段机接线（候选构建、work_dir、stamp 审计、门禁绑定与推进），不是视觉
质量；视觉评审与游戏验收保持 PENDING。渲染是真实 preview3d 渲染（--size 控制）。

任一阶段门禁不通过：记录阻塞原因、以 operator 拒评把门禁结论写入任务（与
agent_review 的软件拒评先例同形），然后停止——门禁语义不许绕过。

    PYTHONPATH=src python -X utf8 tools/atelier_atlas_probe.py [--size 256]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(ROOT / 'src'))

from paris_builder import atelier_workflow as a  # noqa: E402
from paris_builder import workflow as w  # noqa: E402
from paris_builder.learning import read_json  # noqa: E402

RUN = 'ATELIER-ATLAS-PROBE'
PROBE_STAGES = ('frameworks', 'facades', 'tier2')

# 离线夹具证据行：真实库件 id 作四层检索候选；内容只供阶段机结构校验，不作研究结论。
EVIDENCE = {
    'structure': 'v4:st1-corner-turret-base',
    'facade': 'v4:st1-window-bay-noble',
    'technique': 'v4:st1-cornice',
    'component': 'v4:st1-dormer-lower',
}


def offline_inputs():
    ids = list(EVIDENCE.values())
    intent = {
        'run': RUN, 'request': '离线探针：街区1件库 atlas_street1 转角公寓的阶段机接线验证（非质量评审）',
        'form': 'corner_house', 'scheme': 'haussmann_apartment',
        'width': 46, 'depth': 42, 'storeys': 6, 'seed': 1901,
        'detail_profile': 'atlas_street1', 'composition_profile': 'grouped_pavilions',
        'evidence_ids': ids, 'facade_decisions': [], 'research_sources': [],
        'mode': 'offline-probe', 'created_at': 'offline-probe',
    }
    inference = {
        'evidence_ids': ids,
        'architectural_contract': {
            'style': 'Paris Haussmann',
            'invariants': ['离线探针：转角塔亭+两翼街面体量', '源层序由件库持有'],
            'variation_axes': ['massing', 'opening_rhythm'],
            'relationships': [],
            'uncertainties': ['离线夹具，不构成研究结论'],
        },
        'research_evidence': {
            'sources': [{'url': 'offline-probe://fixture/%d' % i,
                         'observations': ['离线夹具观察：仅满足研究门禁结构，不作来源证据']}
                        for i in range(3)],
            'design_inferences': ['离线夹具推断：造型先于细节'],
            'boundaries': ['离线夹具边界：不声称来源完备性'],
        },
        'facade_decisions': [], 'unsupported_decisions': [],
    }
    selections = {layer: [{'id': ident, 'layer': layer, 'title': ident,
                           'scope': 'offline probe fixture'}]
                  for layer, ident in EVIDENCE.items()}
    return intent, inference, selections


def reference_names():
    folder = ROOT.parent / '参考图'
    names = [p.name for p in sorted(folder.glob('标准*.png'))]
    names += [p.name for p in sorted(folder.glob('窗对照总览_街面.png'))]
    while len(names) < 5:
        names.append('offline-reference-%d' % len(names))
    return names


def scripted_row(ident, view_keys, decision, refs):
    row = {'id': ident, 'decision': decision,
           'view_observations': {v: '离线探针：视图已真实渲染并哈希绑定；视觉判读 PENDING'
                                 for v in view_keys},
           'reference_comparison': {name: '离线夹具对照记录，不作审美判定' for name in refs},
           'failure_modes': ['无（离线机制探针；不代表视觉质量或游戏验收结论）']}
    if decision == 'pass':
        row['quality_checks'] = {key: {'status': 'pass',
                                       'observation': '机制探针：该轴由确定性门禁与技术校验覆盖，视觉复核 PENDING'}
                                 for key in w.QUALITY_CHECKS}
    else:
        row['quality_checks'] = {key: {'status': 'uncertain',
                                       'observation': '机制探针不做视觉判定；门禁阻塞原因见 conformance 报告'}
                                 for key in w.QUALITY_CHECKS}
    return row


def submit_scripted(folder, decision, rationale):
    task = a.load(folder)
    artifacts = w.current_artifacts(task)
    views_by_candidate = {}
    for artifact in artifacts:
        if artifact['kind'] == 'views':
            views_by_candidate[artifact['candidate']] = set(read_json(artifact['path']))
    refs = reference_names()
    rows = [scripted_row(ident, keys, decision, refs)
            for ident, keys in views_by_candidate.items()] or [scripted_row(None, {}, decision, refs)]
    review = {'stage': task['stage'], 'revision': task['revision'],
              'artifact_hashes': w.bindings(task),
              'reviewer': 'atlas-atelier-probe', 'reviewer_type': 'agent',
              'decision': decision, 'rationale': rationale,
              'scope': 'offline_mechanism_probe',
              'rollback_stage': task['stage'],
              'candidates': rows}
    if task['stage'] in ('frameworks', 'facades'):
        review['selected'] = rows[0]['id']
    return a.submit_review(folder, review)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', default=RUN)
    parser.add_argument('--size', type=int, default=256)
    args = parser.parse_args()
    folder = ROOT / 'runs' / args.run
    evidence = {'run': args.run, 'scope': 'offline mechanism probe; not visual or game acceptance',
                'created': None, 'stages': []}
    if not (folder / 'workflow.json').exists():
        folder.mkdir(parents=True, exist_ok=True)
        intent, inference, selections = offline_inputs()
        a.create(folder, intent, inference, selections)
        evidence['created'] = True
        print('created task via atelier_workflow.create (research/retrieval gates passed structurally)')
    for expected in PROBE_STAGES:
        task = a.load(folder)
        if task['stage'] != expected:
            evidence['stages'].append({'stage': expected, 'outcome': 'NOT_REACHED',
                                       'task_stage': task['stage']})
            break
        stage_dir = folder / ('revision-' + str(task['revision'])) / expected
        print('=== building stage', expected, '===')
        a.build_stage(folder, size=args.size)
        task = a.load(folder)
        technicals = [read_json(art['path']) for art in w.current_artifacts(task)
                      if art['kind'] == 'technical_validation']
        conformances = [read_json(art['path']) for art in w.current_artifacts(task)
                        if art['kind'] == 'architectural_conformance']
        record = {'stage': expected, 'dir': str(stage_dir.relative_to(ROOT)),
                  'technical': [{'status': t['status'],
                                 'stamp_audit': t.get('stamp_audit', {}).get('status'),
                                 'atlas_failures': t.get('atlas_failures')}
                                for t in technicals],
                  'conformance': [{'status': c['status'], 'summary': c['summary']}
                                  for c in conformances]}
        try:
            result = submit_scripted(folder, 'pass',
                '离线机制评审：候选构建、确定性重建、源件审计与门禁绑定证据齐备；视觉质量与游戏验收不在本次范围')
            record['review'] = 'PASS'
            record['stage_after'] = result['stage']
            print('gate PASS →', result['stage'])
        except ValueError as error:
            record['review'] = 'BLOCKED'
            record['gate_reason'] = str(error)[:600]
            print('gate BLOCKED:', str(error)[:300])
            # 把门禁结论写进任务（与软件拒评同形），然后停止：阻塞不绕过。
            reject = submit_scripted(folder, 'reject',
                '门禁未通过（离线探针记录）：' + str(error)[:300])
            record['stage_after'] = reject['stage']
            record['recorded_reject'] = True
            evidence['stages'].append(record)
            break
        evidence['stages'].append(record)
    task = a.load(folder)
    evidence['final'] = {'stage': task['stage'], 'revision': task['revision'],
                         'game_acceptance': task['game_acceptance'],
                         'reviews': [(r['stage'], r['decision']) for r in task['reviews']]}
    out = folder / 'probe_evidence.json'
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(evidence['final'], ensure_ascii=False, indent=2))
    print('wrote', out)


if __name__ == '__main__':
    main()
