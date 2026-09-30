# -*- coding: utf-8 -*-
"""Send the REAL review images to the provider, to separate a payload problem from an outage."""
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

from paris_builder.learning_web import load_key  # noqa: E402
from paris_builder.providers import MultimodalClient, ProviderError  # noqa: E402
from pathlib import Path  # noqa: E402

RUN = Path('runs/ATELIER-A9B3C7EE')
key = os.environ.get('DEEPSEEK_API_KEY') or load_key()
CONFIG = {'model': 'deepseek-flash', 'base_url': 'https://api.deepseek.com', 'vision': True,
          'max_calls': None, 'max_total_tokens': None, 'max_output_tokens': 16000,
          'timeout_seconds': 180,
          'request_options': {'thinking': {'type': 'disabled'}}}

views = sorted(RUN.glob('revision-*/facades/facade-1/views.json'), key=os.path.getmtime)[-1]
data = json.load(io.open(views, encoding='utf-8'))
names = list(data)
print('view bundle:', views)
print('views:', len(names))
paths = [Path(data[n]['path']) for n in names]
for name, path in zip(names, paths):
    print('  %-20s %8.1f KB  exists=%s' % (name, path.stat().st_size / 1024 if path.is_file() else -1,
                                           path.is_file()))

print()
print('=== vision call, 7 images (the batch size the review uses) ===')
for size in (7, 7, 3):
    batch = paths[:size]
    client = MultimodalClient(dict(CONFIG), credential=key)
    try:
        started = time.time()
        result, receipt = client.complete(
            'Inspect every image in order. Return JSON observations: an array of exactly %d short strings.'
            % len(batch), images=batch, max_tokens=2000)
        print('  %d images -> OK in %.1fs, usage %s' % (
            len(batch), time.time() - started,
            json.dumps(receipt.get('usage'), ensure_ascii=False)[:160]))
        print('    keys:', list(result)[:5])
        break
    except ProviderError as error:
        print('  %d images -> ProviderError: %s' % (len(batch), str(error)[:300]))
    except Exception as error:                                        # noqa: BLE001
        print('  %d images -> %s: %s' % (len(batch), type(error).__name__, str(error)[:300]))
    time.sleep(3)
