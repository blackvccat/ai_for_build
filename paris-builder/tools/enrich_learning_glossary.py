"""Bounded DeepSeek terminology expansion. General definitions, not source observations."""
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from paris_builder.learning import ROOT, read_json, now
from paris_builder.providers import MultimodalClient

def main():
    if not os.environ.get('DEEPSEEK_API_KEY'):
        raise SystemExit('Set DEEPSEEK_API_KEY for this process only')
    families = read_json(ROOT / 'knowledge/library-v1/catalog.json')['families']
    client = MultimodalClient({'base_url': 'https://api.deepseek.com', 'model': 'deepseek-flash',
                              'max_calls': 3, 'max_total_tokens': 15000, 'max_output_tokens': 3500,
                              'timeout_seconds': 90, 'request_options': {'thinking': {'type': 'disabled'}},
                              'raw_reply_dir': str(ROOT / 'runs/LEARNING-WORKBENCH-v1/model-replies')})
    items = list(families.items())
    definitions, receipts = {}, []
    for start in range(0, len(items), 15):
        batch = dict(items[start:start+15])
        prompt = ('为建筑知识检索生成中文通用术语释义。只解释术语的一般用途，不声称看过本项目的源建筑，'
                  '不规定 Minecraft 固定尺寸或材料，不宣称实例正确。每项一到两句，45至90个汉字，'
                  '解释常见位置、功能、与邻近构件的关系，涵盖用户可能使用的普通说法。'
                  '返回 JSON 对象 {"definitions": {"提供的英文id": "中文释义"}}。必须准确包含全部给定id，不能新增。'
                  '\n术语：' + json.dumps(batch, ensure_ascii=False))
        result, receipt = client.complete(prompt, max_tokens=3500)
        rows = result.get('definitions')
        if not isinstance(rows, dict) or set(rows) != set(batch) or not all(isinstance(v,str) and 10 < len(v) < 500 for v in rows.values()):
            raise ValueError('Invalid terminology output; not saved')
        definitions.update(rows);receipts.append(receipt)
        print('Terminology batch complete:', len(definitions), '/', len(families), flush=True)
    out = ROOT / 'knowledge/learning/technique_glossary.json'
    data = {'created_at': now(), 'status': 'MODEL_GENERATED_GENERAL_TERMINOLOGY',
            'scope': '通用建筑术语释义；不是对源裁件的观察，不构成源技法或优秀程度确认。',
            'definitions': definitions, 'receipts': receipts}
    out.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Saved', len(definitions), 'definitions; total tokens:', client.tokens)

if __name__ == '__main__': main()
