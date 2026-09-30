"""校验网页里的 <script> 语法，并核对几个关键接口。

为什么需要它：页面脚本是从宿主模板字符串里生成的，任何一处转义失误都会让浏览器端整段脚本
静默不执行——表现只是"页面停在载入中…"，没有任何可见错误。这个坑真实发生过一次：
`'\\n'` 在模板字符串里被先消化成真实换行，JS 字符串字面量断行，整个页面挂掉。

所以每次改页面，先跑这个：
  1. 取回页面；
  2. 抽出 <script> 交给 `node --check`（真正的 JS 解析器，不靠肉眼）；
  3. 顺带确认 runs / run / asset 三个接口仍然可用。

用法：python tools\\check_web_page.py [--url http://127.0.0.1:3080/building] [--run CHAIN-v1.0]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))

from paris_builder.fonts import node_binary  # noqa: E402


def fetch(url: str, timeout: float = 30.0) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode('utf-8', errors='replace')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:3080/building')
    parser.add_argument('--run', default=None, help='额外检查这个 run 的详情接口')
    args = parser.parse_args()

    html = fetch(args.url)
    print('page: %d bytes' % len(html))

    scripts = re.findall(r'<script>(.*?)</script>', html, re.S)
    if not scripts:
        print('FAIL: no <script> block found')
        return 1
    node = node_binary()
    tmp = pathlib.Path(tempfile.gettempdir()) / 'dsh_page_check.js'
    failed = 0
    for index, body in enumerate(scripts):
        tmp.write_text(body, encoding='utf-8')
        result = subprocess.run([node, '--check', str(tmp)], capture_output=True, text=True,
                                encoding='utf-8', errors='replace')
        verdict = 'OK' if result.returncode == 0 else 'FAIL'
        print('script %d: %d bytes -> %s' % (index, len(body), verdict))
        if result.returncode != 0:
            failed += 1
            print((result.stderr or result.stdout).strip()[:2000])

    base = args.url[:args.url.rindex('/')] if '/' in args.url[len('http://'):] else args.url
    base = args.url.rsplit('/building', 1)[0] + '/building'
    try:
        runs = json.loads(fetch(base + '/api/runs'))
        print('api/runs: %d runs, root=%s' % (len(runs.get('runs') or []), runs.get('root')))
        if runs.get('error'):
            print('  warning: %s' % runs['error'])
    except Exception as error:                                        # noqa: BLE001
        failed += 1
        print('api/runs FAIL: %s' % error)

    name = args.run
    if name is None:
        candidates = [r['name'] for r in (runs.get('runs') or []) if r.get('stages_done')]
        name = candidates[0] if candidates else None
    if name:
        try:
            state = json.loads(fetch(base + '/api/run?name=' + name))
            print('api/run %s: %s/%s stages, %d acceptance=%s' % (
                name, state.get('stages_done'), state.get('stages_total'),
                len(state.get('stages') or []),
                (state.get('acceptance') or {}).get('status', 'PENDING')))
        except Exception as error:                                    # noqa: BLE001
            failed += 1
            print('api/run FAIL: %s' % error)

    print('\nverdict: %s' % ('PASS' if failed == 0 else 'FAIL (%d)' % failed))
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
