"""Predeclared development retrieval cases, not an independent aesthetic benchmark."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from paris_builder.learning import KnowledgeIndex, ROOT, now

CASES = [
    ('顺着坡道逐段降低的房屋', 'structure', {'structure:slope_terrace'}),
    ('前院和左右翼楼围合的府邸', 'structure', {'structure:court_palace'}),
    ('连续街道上不同高度的联排房屋', 'structure', {'structure:street_row'}),
    ('窄而深的宅基地，两边共墙', 'structure', {'structure:street_house'}),
    ('普通住宅，均匀窗户，装饰克制', 'facade', {'facade:plain_terrace'}),
    ('底层连续的商店橱窗和招牌', 'facade', {'facade:shop_terrace'}),
    ('用中央入口与高窗突出府邸仪式感', 'facade', {'facade:palace_front'}),
    ('屋顶上排烟的烟囱', 'technique', {'technique:chimney'}),
    ('雨水从屋顶沿墙排下来', 'technique', {'technique:downpipe', 'technique:gutter'}),
    ('屋面上凸出来的小窗', 'technique', {'technique:dormer'}),
    ('入口遮雨的棚子', 'technique', {'technique:awning'}),
    ('窗框里面的竖向分隔', 'technique', {'technique:mullion'}),
    ('屋顶烟囱', 'component', {'v1:chimney-v1', 'v1:chimney-v2', 'v1:chimney-v3'}),
    ('门口入口门廊', 'component', {'v1:portal-v1', 'v1:portal-v2', 'v1:portal-v3'}),
]

def main():
    index = KnowledgeIndex()
    results = []
    for query, layer, expected in CASES:
        rows = index.query(query, layer=layer, limit=3)['items']
        ids = [r['id'] for r in rows]
        results.append({'query': query, 'layer': layer, 'expected_any': sorted(expected),
                        'top3': ids, 'pass': bool(expected.intersection(ids))})
    constrained = index.query('精致窗户', layer='component', max_width=3, vanilla=True, limit=100)['items']
    results.append({'query': '精致窗户 / 面宽≤3 / 原版', 'returned': len(constrained),
                    'pass': bool(constrained) and all(r['dimensions'][0] <= 3 and index.by_id[r['id']]['compatible_vanilla'] for r in constrained)})
    report = {'created_at': now(), 'total': len(results), 'passed': sum(x['pass'] for x in results),
              'scope': '开发者预设的分层 Top-3 冒烟评测；不是独立人工评测，不证明美学质量或完整建筑理解。失败案例保留，不调整阈值掩盖失败。',
              'cases': results}
    out = ROOT / 'runs/LEARNING-WORKBENCH-v1/benchmark.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == '__main__': main()
