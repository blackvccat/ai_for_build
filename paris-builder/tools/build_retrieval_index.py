#!/usr/bin/env python3
import json
import argparse
import urllib.request
from pathlib import Path
from paris_builder.retrieval import build_index, MODEL_ID, MODEL_REVISION

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--download-model', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.download_model:
        out = root / 'knowledge/retrieval/model'
        out.mkdir(parents=True, exist_ok=True)
        for name in ['onnx/model_qint8_arm64.onnx', 'tokenizer.json', 'config.json', 'README.md']:
            target = out / Path(name).name
            if not target.exists():
                temporary = target.with_suffix(target.suffix + '.download')
                urllib.request.urlretrieve('https://huggingface.co/' + MODEL_ID + '/resolve/' + MODEL_REVISION + '/' + name, temporary)
                temporary.replace(target)
    manifest = build_index(root)
    print(json.dumps({k: v for k, v in manifest.items() if k != 'ids'}, ensure_ascii=False, indent=2))
