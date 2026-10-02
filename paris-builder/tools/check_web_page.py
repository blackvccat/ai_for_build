"""校验网页里的 <script> 语法，并核对几个关键接口。

为什么需要它：页面脚本是从宿主模板字符串里生成的，任何一处转义失误都会让浏览器端整段脚本
静默不执行——表现只是"页面停在载入中…"，没有任何可见错误。这个坑真实发生过一次：
`'\\n'` 在模板字符串里被先消化成真实换行，JS 字符串字面量断行，整个页面挂掉。

所以每次改页面，先跑这个：
  1. 取回页面；
  2. 获取内联及外链 <script>，交给 `node --check`（真正的 JS 解析器，不靠肉眼）；
  3. 顺带确认 runs / run 接口仍然可用（兼容学习工坊及宿主 /building）。

用法：python tools\\check_web_page.py [--url http://127.0.0.1:3080/building] [--run CHAIN-v1.0]
      python tools\\check_web_page.py --url http://127.0.0.1:8765 --run ATELIER-A9B3C7EE
"""
from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
import pathlib
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))

from paris_builder.fonts import node_binary  # noqa: E402


def fetch(url: str, timeout: float = 30.0) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode('utf-8', errors='replace')


class PageScripts(HTMLParser):
    """Collect executable scripts; JSON data blocks do not contain JavaScript."""

    def __init__(self):
        super().__init__()
        self.scripts: list[tuple[dict, str]] = []
        self.current: dict | None = None
        self.body: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.current = dict(attrs)
            self.body = []

    def handle_data(self, data):
        if self.current is not None:
            self.body.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.current is not None:
            script_type = (self.current.get('type') or '').strip().lower()
            if script_type in ('', 'module', 'text/javascript', 'application/javascript',
                               'text/ecmascript', 'application/ecmascript'):
                self.scripts.append((self.current, ''.join(self.body)))
            self.current = None


def api_routes(page_url: str) -> tuple[str, str, str]:
    """The host plugin uses /building/api; the standalone workbench uses /api/design."""
    parsed = urllib.parse.urlsplit(page_url)
    origin = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, '', '', ''))
    if parsed.path.rstrip('/') == '/building' or parsed.path.startswith('/building/'):
        return origin + '/building/api/runs', origin + '/building/api/run', 'runs'
    return origin + '/api/design/runs', origin + '/api/design/run', 'items'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8765')
    parser.add_argument('--run', default=None, help='额外检查这个 run 的详情接口')
    args = parser.parse_args()

    try:
        html = fetch(args.url)
    except Exception as error:                                        # noqa: BLE001
        print('page FAIL: %s' % error)
        return 1
    print('page: %d bytes' % len(html.encode('utf-8')))

    page = PageScripts()
    page.feed(html)
    if not page.scripts:
        print('FAIL: no executable <script> block found')
        return 1
    node = node_binary()
    failed = 0
    with tempfile.TemporaryDirectory(prefix='paris_page_check_') as temporary:
        for index, (attrs, inline_body) in enumerate(page.scripts):
            source = urllib.parse.urljoin(args.url, attrs['src']) if attrs.get('src') else 'inline'
            try:
                body = fetch(source) if attrs.get('src') else inline_body
                extension = '.mjs' if (attrs.get('type') or '').strip().lower() == 'module' else '.js'
                tmp = pathlib.Path(temporary) / ('script-%d' % index + extension)
                tmp.write_text(body, encoding='utf-8')
                result = subprocess.run([node, '--check', str(tmp)], capture_output=True, text=True,
                                        encoding='utf-8', errors='replace')
                verdict = 'OK' if result.returncode == 0 else 'FAIL'
                print('script %d (%s): %d bytes -> %s' % (
                    index, source, len(body.encode('utf-8')), verdict))
                if result.returncode != 0:
                    failed += 1
                    print((result.stderr or result.stdout).strip()[:2000])
            except Exception as error:                                # noqa: BLE001
                failed += 1
                print('script %d (%s) FAIL: %s' % (index, source, error))

    runs_url, run_url, rows_key = api_routes(args.url)
    rows = []
    try:
        runs = json.loads(fetch(runs_url))
        rows = runs[rows_key]
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError('%s must be a list of run objects' % rows_key)
        print('%s: %d runs' % (urllib.parse.urlsplit(runs_url).path, len(rows)))
        if runs.get('error'):
            raise ValueError(runs['error'])
    except Exception as error:                                        # noqa: BLE001
        rows = []
        failed += 1
        print('%s FAIL: %s' % (urllib.parse.urlsplit(runs_url).path, error))

    name = args.run
    if name is None:
        candidates = ([r['name'] for r in rows if r.get('stages_done') and r.get('name')]
                      if rows_key == 'runs' else [r['run'] for r in rows if r.get('run')])
        name = candidates[0] if candidates else None
    if name:
        try:
            state = json.loads(fetch(run_url + '?' + urllib.parse.urlencode({'name': name})))
            if state.get('error'):
                raise ValueError(state['error'])
            if rows_key == 'items':
                if state.get('run') != name or not isinstance(state.get('intent'), dict):
                    raise ValueError('run response has missing or mismatched run/intent')
                workflow = state.get('workflow') or {}
                status = workflow.get('status') or {}
                report = state.get('report') or {}
                print('api/design/run %s: stage=%s, revision=%s, acceptance=%s' % (
                    name, status.get('stage') or (state.get('build_status') or {}).get('status'),
                    status.get('revision'), status.get('game_acceptance') or
                    report.get('game_acceptance', 'PENDING')))
            else:
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
