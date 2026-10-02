# -*- coding: utf-8 -*-
"""Why does facades never pass? Characterise the failures rather than the scores.

Two very different worlds produce "22 rejects in a row":
  * WHACK-A-MOLE - each round fails a different check; repairs fix one, break another.
  * SAME WALL     - the same 2-3 checks fail every round; the repair loop cannot move them.

The remedy is completely different, so measure which one this is.
"""
import io
import json
import re
from collections import Counter

w = json.load(io.open('runs/ATELIER-A9B3C7EE/workflow.json', encoding='utf-8'))

rows = []
for r in w['reviews']:
    if r['stage'] != 'facades' or (r.get('revision') or 0) < 45:
        continue
    for c in r.get('candidates', []):
        fails = []
        groups = [('geometry', c.get('geometry_checks') or {})]
        groups += [('layer:' + k, v) for k, v in (c.get('detail_checks') or {}).items()]
        groups += [('storey:' + k, v) for k, v in (c.get('storey_checks') or {}).items()]
        for name, group in groups:
            for key, value in (group or {}).items():
                if isinstance(value, dict) and value.get('status') == 'fail':
                    fails.append('%s/%s' % (name, key))
        for key, value in (c.get('layer_checks') or {}).items():
            if isinstance(value, dict) and value.get('status') == 'fail':
                fails.append('layercheck/' + key)
        scores = c.get('scores')
        rows.append({'rev': r.get('revision'), 'total': sum(scores) if scores and len(scores) == 5 else None,
                     'fails': sorted(fails),
                     'modes': [str(x) for x in (c.get('failure_modes') or [])]})

print('=== 每轮：分数 / 失败检查项数 / 失败项 ===')
for row in rows:
    print('  rev %-4s total=%-4s fails=%d  %s' % (row['rev'], row['total'], len(row['fails']),
                                                  ', '.join(row['fails'])[:110]))

print()
print('=== 失败项出现频率（22 轮）===')
counter = Counter(f for row in rows for f in row['fails'])
for name, count in counter.most_common(18):
    bar = '#' * count
    print('  %-34s %2d  %s' % (name, count, bar))

counts = [len(row['fails']) for row in rows]
print()
print('失败项数: min=%d max=%d mean=%.1f' % (min(counts), max(counts), sum(counts) / len(counts)))
print('  分布:', dict(sorted(Counter(counts).items())))

print()
print('=== 分数 vs 失败项数 ==="')
pairs = [(row['total'], len(row['fails'])) for row in rows if row['total'] is not None]
high_score = [f for t, f in pairs if t >= 80]
low_score = [f for t, f in pairs if t < 80]
if high_score:
    print('  分数>=80 的轮次 (%d): 失败项数 %s  mean=%.1f' % (len(high_score), high_score, sum(high_score) / len(high_score)))
if low_score:
    print('  分数< 80 的轮次 (%d): 失败项数 %s  mean=%.1f' % (len(low_score), low_score, sum(low_score) / len(low_score)))

print()
print('=== 失败描述里的关键词（找"反复出现的同一句话"）===')
text = ' '.join(row['modes'][0] if row['modes'] else '' for row in rows)
text = ' '.join(str(m) for row in rows for m in row['modes'])
for phrase in ('证据', '不确定', '无法', '缺乏', '未见', '冲突', '矛盾', '遮挡', '不可读',
               '连续', '贯通', '交圈', '凹', '坡折', 'mansard', '切角', '阳台'):
    print('  %-10s %d' % (phrase, text.count(phrase)))
