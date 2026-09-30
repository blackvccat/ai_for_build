# -*- coding: utf-8 -*-
"""Probe the model provider directly, so a run failure is not misread as a code failure."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

from paris_builder.learning_web import load_key  # noqa: E402
from paris_builder.providers import MultimodalClient, ProviderError  # noqa: E402

key = os.environ.get('DEEPSEEK_API_KEY') or load_key()
print('key present:', bool(key), '| length:', len(key) if key else 0)

CONFIG = {'model': 'deepseek-flash', 'base_url': 'https://api.deepseek.com', 'vision': True,
          'max_calls': None, 'max_total_tokens': None, 'max_output_tokens': 16000,
          'timeout_seconds': 180,
          'request_options': {'thinking': {'type': 'disabled'}}}

print()
print('=== attempt 1: tiny text call (no images) ===')
for attempt in range(3):
    client = MultimodalClient(dict(CONFIG), credential=key)
    try:
        started = time.time()
        result, receipt = client.complete('Reply with exactly {"ok": true} and nothing else.', images=[], max_tokens=64)
        print('  OK in %.1fs -> %s' % (time.time() - started, str(result)[:120]))
        print('  usage:', json.dumps(receipt.get('usage'), ensure_ascii=False)[:200])
        break
    except ProviderError as error:
        print('  attempt %d ProviderError: %s' % (attempt + 1, str(error)[:400]))
    except Exception as error:                                        # noqa: BLE001
        print('  attempt %d %s: %s' % (attempt + 1, type(error).__name__, str(error)[:400]))
    time.sleep(3)

print()
print('=== balance endpoint ===')
import urllib.request                                                # noqa: E402
request = urllib.request.Request('https://api.deepseek.com/user/balance',
                                 headers={'Authorization': 'Bearer ' + key})
try:
    with urllib.request.urlopen(request, timeout=30) as response:
        print(' ', response.status, response.read().decode('utf-8')[:400])
except Exception as error:                                            # noqa: BLE001
    print('  balance probe failed:', type(error).__name__, str(error)[:400])
    if hasattr(error, 'read'):
        try:
            print('  body:', error.read().decode('utf-8')[:400])
        except Exception:                                             # noqa: BLE001
            pass
