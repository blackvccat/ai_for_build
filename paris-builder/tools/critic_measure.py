#!/usr/bin/env python3
"""Ask the visual critic to score the current framework geometry (route C measure).

Builds one framework candidate with the same concept the earlier live run used,
renders the review images, and sends them to the same critic prompt the pipeline
uses, so the score is comparable with the recorded fw2 = 77 (15,16,15,15,16).

This is a measurement, not a gate: it writes a comparison report and never claims
user acceptance.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from paris_builder.executor import (build_candidate, candidate_image_labels,  # noqa: E402
                                    candidate_images, look_instruction)
from paris_builder.providers import MultimodalClient, ProviderError  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    parser.add_argument('--concept', type=Path, required=True, help='concept.json to render')
    parser.add_argument('--provider', default='configs/providers/deepseek.run.json')
    parser.add_argument('--size', type=int, default=420)
    parser.add_argument('--label', default='after-B')
    parser.add_argument('--no-ornament', action='store_true',
                        help='disable the route-B extras, to measure their effect')
    parser.add_argument('--strips', action='store_true',
                        help='build street facades from mined source sections (route A2)')
    args = parser.parse_args()

    run_dir = ROOT / 'runs' / args.run
    run_dir.mkdir(parents=True, exist_ok=True)
    concept = json.loads(args.concept.read_text(encoding='utf-8'))
    # Framework layer, framework path: commercial ground floor, role hierarchy,
    # stepped crown and coursed stone all active.
    built = build_candidate(concept, run_dir / 'candidate', stage=1, scheme=1, size=args.size,
                            ornament=not args.no_ornament, strips=args.strips)
    config = json.loads((ROOT / args.provider).read_text(encoding='utf-8'))
    client = MultimodalClient(config)
    references = sorted((ROOT.parent / '参考图').glob('标准*.png')) + [ROOT.parent / '参考图' / '窗对照总览_街面.png']
    labels = {p.name: 'standard reference' for p in references if p.exists()}
    brief = json.loads((ROOT / 'knowledge/workflow/brief.example.json').read_text(encoding='utf-8'))
    prompt = look_instruction(brief, built['candidate_id'],
                              candidate_image_labels(built['render_paths']), labels, 'frameworks')
    images = candidate_images(built) + [p for p in references if p.exists()]
    result, receipt = client.complete(prompt, images, max_tokens=8000)
    (run_dir / 'look.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    scores = result.get('scores') or []
    report = {
        'label': args.label,
        'candidate': built['candidate_id'],
        'decision': result.get('decision'),
        'scores': scores,
        'total': sum(s for s in scores if isinstance(s, (int, float))),
        'mean': round(sum(s for s in scores if isinstance(s, (int, float))) / len(scores), 2) if scores else None,
        'failure_modes': result.get('failure_modes'),
        'view_observations': len(result.get('view_observations') or {}),
        'baseline_for_comparison': {'label': 'before-B (MODEL-DESIGN-LIVE-v0.8 fw2)',
                                    'scores': [15, 16, 15, 15, 16], 'total': 77, 'mean': 15.4},
        'usage': receipt['usage'],
        'note': 'Provider-neutral critic score used as a measurement of geometry changes; '
                'it is not a gate and not user acceptance.',
    }
    (run_dir / 'critic_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('label', 'decision', 'scores', 'total', 'mean')}, ensure_ascii=False))
    print('failure modes:', json.dumps(report['failure_modes'], ensure_ascii=False)[:400])


if __name__ == '__main__':
    try:
        main()
    except ProviderError as error:
        print('PROVIDER_ERROR:', error, file=sys.stderr)
        raise SystemExit(2)
