#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from paris_builder.retrieval import ComponentIndex

if __name__ == '__main__':
    p = argparse.ArgumentParser(description='Retrieve candidates; never implies construction approval')
    p.add_argument('text')
    p.add_argument('--family'); p.add_argument('--max-width', type=int); p.add_argument('--max-depth', type=int)
    p.add_argument('--limit', type=int, default=5); p.add_argument('--reference-image')
    p.add_argument('--dimensions', type=float, nargs=3); p.add_argument('--game-status')
    p.add_argument('--full', action='store_true')
    a = vars(p.parse_args()); full = a.pop('full')
    index = ComponentIndex(Path(__file__).resolve().parents[1] / 'knowledge/retrieval')
    results = index.query(**a)
    if not full:
        for r in results: r.pop('evidence')
    print(json.dumps(results, ensure_ascii=False, indent=2))
