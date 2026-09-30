#!/usr/bin/env python3
"""Persist a provider-neutral workflow. No API credentials or model assumptions."""
import argparse
import json
from pathlib import Path
from paris_builder import workflow as w

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['create', 'register', 'review', 'advance', 'rollback', 'status', 'prompt', 'materials', 'compare'])
    p.add_argument('--task', required=True)
    p.add_argument('--json', help='Brief/review JSON file')
    p.add_argument('--model', default='unspecified')
    p.add_argument('--image-input', action='store_true', help='Declaration only; live probe remains required')
    p.add_argument('--kind'); p.add_argument('--path'); p.add_argument('--candidate')
    p.add_argument('--target'); p.add_argument('--reason'); p.add_argument('--other', action='append', default=[])
    a = p.parse_args()
    if a.action == 'create':
        if Path(a.task).exists(): p.error('Task already exists')
        result = w.create_task(a.task, json.loads(Path(a.json).read_text( encoding="utf-8")), a.model, {'image_input': a.image_input})
    else:
        t = w.load(a.task)
        if a.action == 'register': result = w.register_artifact(t, a.kind, a.path, a.candidate)
        elif a.action == 'review':
            w.submit_review(t, json.loads(Path(a.json).read_text( encoding="utf-8"))); result = w.status(t)
        elif a.action == 'advance': result = w.advance(t)
        elif a.action == 'rollback': w.rollback(t, a.target, a.reason); result = w.status(t)
        elif a.action == 'prompt': result = w.prompt(t)
        elif a.action == 'compare': result = w.compare_runs([t] + [w.load(x) for x in a.other])
        elif a.action == 'materials':
            root = Path(__file__).resolve().parents[1]
            result = {'style_models': str(root/'knowledge/styles'), 'components': str(root/'knowledge/library-v1/catalog.json'),
                      'references': str(root.parent/'参考图'), 'registered': t['artifacts'],
                      'retrieval': 'Use tools/query_components.py --help for installed retrieval interface'}
        else: result = w.status(t)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__': main()
