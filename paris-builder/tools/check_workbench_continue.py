"""Read-only live continuation checks plus isolated session/review UI checks.

No live POST is sent. The delete/undo and review-save paths use browser route
fixtures, so this cannot advance a workflow or record Minecraft acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
VIEWS = ('front', 'back', 'left', 'right', 'top', 'axonometric_front', 'axonometric_back')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8765')
    parser.add_argument('--run', default='ATELIER-A9B3C7EE')
    parser.add_argument('--history-run', default='ATELIER-54E0BBBA')
    parser.add_argument('--out', type=Path,
                        default=ROOT / 'runs/LEARNING-WORKBENCH-v1/browser/continued-20261001')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    report = {'status': 'RUNNING', 'checks': [], 'page_errors': [], 'live_post_requests': [],
              'scope': 'live read-only; session delete/undo and review saving are isolated browser fixtures'}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1100})
        page = context.new_page()
        page.on('pageerror', lambda error: report['page_errors'].append(str(error)))
        page.on('request', lambda request: report['live_post_requests'].append(request.url)
                if request.method == 'POST' else None)
        try:
            sessions = context.request.get(args.url + '/api/agent/sessions').json()['items']
            assert sessions, 'No persisted session available for restoration'
            session = sessions[0]['id']
            snapshot = context.request.get(args.url + '/api/agent/session?' + urlencode({'id': session})).json()
            first = next(event['text'] for event in snapshot['events'] if event['kind'] == 'user')
            report['session'] = {'id': session, 'events': len(snapshot['events']), 'task': snapshot['task']}
            page.goto(args.url + '/#studio', wait_until='domcontentloaded')
            page.locator('[data-agent-session="' + session + '"]').click()
            page.wait_for_function('(title) => document.querySelector("#studio-session-label")?.textContent === title', arg=first[:48])
            assert page.locator('#agent-timeline .agent-event').count() > 0
            page.screenshot(path=str(args.out / 'session-restored.png'), full_page=True)
            page.reload(wait_until='domcontentloaded')
            page.wait_for_function('(title) => document.querySelector("#studio-session-label")?.textContent === title', arg=first[:48])
            assert page.locator('#agent-session-select').input_value() == session
            report['checks'].append('persisted_session_restored_after_reload')

            page.locator('[data-studio-tab="trace"]').click()
            page.wait_for_timeout(4700)
            assert page.locator('#studio-view-trace').is_visible()
            assert page.locator('#studio-view-preview').is_hidden()
            report['checks'].append('background_session_refresh_keeps_trace_view')

            page.locator('[data-studio-tab="preview"]').click()
            page.locator('#design-history [data-design-run="' + args.run + '"]').click()
            page.locator('#design-result .eyebrow').filter(has_text=args.run).wait_for()
            current = context.request.get(args.url + '/api/design/run?' + urlencode({'name': args.run})).json()['workflow']
            report['workflow'] = {key: current.get(key) for key in ('status', 'ready_for_review', 'delivery')}
            report['workflow']['job_status'] = (current.get('job') or {}).get('status')
            text = page.locator('#design-result').inner_text()
            assert '修订 ' + str(current['status']['revision']) in text
            assert '游戏验收 ' + current['status']['game_acceptance'] in text
            if not current['delivery']:
                assert page.locator('#design-result a[href*="delivery.zip"]').count() == 0
                assert page.locator('#workflow-game').count() == 0
            last = (current.get('history') or [{}])[-1]
            busy = (current.get('job') or {}).get('status') in ('queued', 'running', 'stopping')
            if last.get('rollback_from') and last.get('to') == current['status']['stage'] and not busy:
                assert last['reason'] in page.locator('#workflow-message').inner_text()
                assert '已从' in page.locator('#workflow-message').inner_text()
                report['checks'].append('rollback_reason_displayed_instead_of_previous_revision_pass')
            latest = current.get('latest_review') or {}
            if latest and latest.get('revision') != current['status']['revision']:
                assert '此前阶段评审 · 修订 ' + str(latest['revision']) in page.locator('[data-latest-review] summary').inner_text()
            source_reports = []
            for candidate in current.get('candidates') or []:
                panel = page.locator('[data-candidate="' + candidate['id'] + '"]')
                evidence = candidate.get('source_state_evidence')
                if not evidence:
                    assert panel.locator('[data-source-state]').count() == 0
                    continue
                if not panel.evaluate('element => element.open'):
                    panel.locator(':scope > summary').click()
                summary = panel.locator('[data-source-state]')
                assert summary.is_visible()
                coverage = evidence.get('opening_coverage') or []
                passed = sum(row['status'] == 'PASS' for row in coverage)
                assert f'{passed} / {len(coverage)} 扇窗通过' in summary.inner_text()
                assert '来源构法核对 · ' + evidence['status'] in summary.inner_text()
                assert '核对范围：北街与东街住宅窗' in summary.inner_text()
                assert '游戏验收：PENDING' in summary.inner_text()
                source_reports.append({'id': candidate['id'], 'status': evidence['status'],
                                       'covered_windows': passed, 'windows': len(coverage)})
            if source_reports:
                report['source_method_reports'] = source_reports
                report['checks'].append('source_method_badge_and_window_counts_match_candidate_evidence')
            report['checks'].append('current_workflow_stage_revision_acceptance_and_delivery_match_api')
            page.screenshot(path=str(args.out / 'current-workflow.png'), full_page=True)

            page.locator('#design-history [data-design-run="' + args.history_run + '"]').click()
            page.locator('#design-result .eyebrow').filter(has_text=args.history_run).wait_for()
            history = context.request.get(args.url + '/api/design/run?' + urlencode({'name': args.history_run})).json()['workflow']
            assert history['delivery']
            for view in VIEWS:
                page.locator('[data-final-view="' + view + '"]').click()
                page.wait_for_function('document.querySelector("#workflow-final-image")?.complete && document.querySelector("#workflow-final-image")?.naturalWidth > 0')
                src = page.locator('#workflow-final-image').get_attribute('src')
                response = context.request.get(args.url + src, max_retries=2)
                assert response.ok
                assert hashlib.sha256(response.body()).hexdigest() == history['preview'][view]['sha256']
            report['checks'].append('historical_delivery_seven_view_controls_and_image_hashes')
            downloads = []
            for link in page.locator('#design-result a[href*="/api/workflow/file"]').all():
                href = link.get_attribute('href')
                response = context.request.get(args.url + href, max_retries=2)
                assert response.ok
                filename = response.headers.get('content-disposition', '').split('filename=')[-1].strip('"')
                assert filename.endswith(('.schem', '.zip')), filename
                params = parse_qs(urlsplit(href).query)
                local_file = ROOT / 'runs' / params['run'][0] / params['path'][0]
                digest = hashlib.sha256(response.body()).hexdigest()
                assert digest == hashlib.sha256(local_file.read_bytes()).hexdigest()
                downloads.append({'label': link.inner_text(), 'filename': filename, 'bytes': len(response.body()),
                                  'sha256': digest, 'matches_disk_artifact': True})
            assert len(downloads) == 3
            report['downloads'] = downloads
            report['checks'].append('historical_zip_and_both_schematics_download_with_file_headers')
            assert page.locator('#game-decision').input_value() == 'rejected'
            assert page.locator('[data-game]:checked').count() == 0
            assert '游戏验收 PENDING' in page.locator('#design-result').inner_text()
            page.screenshot(path=str(args.out / 'historical-delivery.png'), full_page=True)
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile studio horizontal overflow'
            page.screenshot(path=str(args.out / 'studio-mobile.png'), full_page=True)
            report['checks'].append('studio_mobile_no_horizontal_overflow')
            assert not report['live_post_requests'], report['live_post_requests']

            fixture_context = browser.new_context(viewport={'width': 1440, 'height': 1100})
            fixture_page = fixture_context.new_page()
            fixture_page.on('pageerror', lambda error: report['page_errors'].append(str(error)))
            fixture_session = 'browser-fixture-session'
            fixture_run = 'ATELIER-BROWSER-FIXTURE'
            fixture = {'deleted': False, 'review': None, 'writes': []}
            # Reuse a real completed draft's response only as immutable UI shape evidence.
            draft = context.request.get(args.url + '/api/design/run?name=ATELIER-BD836BD3').json()
            draft['run'] = fixture_run
            draft['intent']['session'] = fixture_session
            draft['intent']['request'] = '浏览器夹具：巴黎公寓'
            draft['visual_review'] = None

            def fixture_route(route):
                request = route.request
                path = urlsplit(request.url).path
                if path == '/api/agent/sessions':
                    value = {'items': [] if fixture['deleted'] else [{'id': fixture_session,
                        'title': '浏览器夹具：巴黎公寓', 'created_at': '2026-10-01T00:00:00Z', 'event_count': 2}]}
                elif path == '/api/agent/session':
                    value = {'id': fixture_session, 'active': False, 'task': {'status': 'idle'},
                             'events': [{'kind': 'user', 'text': '浏览器夹具：巴黎公寓'},
                                        {'kind': 'tool_result', 'run': fixture_run, 'status': 'PASS'}]}
                elif path == '/api/agent/session/delete':
                    fixture['deleted'] = True
                    value = {'id': fixture_session, 'status': 'deleted', 'building_files': 'preserved'}
                elif path == '/api/agent/session/restore':
                    fixture['deleted'] = False
                    value = {'id': fixture_session, 'status': 'restored'}
                elif path == '/api/agent/events':
                    route.fulfill(status=200, content_type='text/event-stream', body=': fixture\n\n')
                    return
                elif path == '/api/design/runs':
                    value = {'items': [{'run': fixture_run, 'intent': draft['intent'], 'status': 'PASS'}]}
                elif path == '/api/design/run':
                    value = {**draft, 'visual_review': fixture['review']}
                elif path == '/api/design/file':
                    route.fulfill(status=200, content_type='image/png', body=(ROOT / 'runs/ATELIER-BD836BD3/tier-3-previews/front.png').read_bytes())
                    return
                elif path == '/api/design/review':
                    fixture['review'] = {**request.post_data_json, 'at': '2026-10-01T00:00:00Z',
                                         'scope': 'rendered_visual_review_only', 'game_acceptance': 'PENDING'}
                    value = fixture['review']
                else:
                    route.continue_()
                    return
                if request.method == 'POST':
                    fixture['writes'].append({'path': path, 'body': request.post_data_json})
                route.fulfill(status=200, content_type='application/json', body=json.dumps(value, ensure_ascii=False))

            fixture_page.route('**/api/agent/**', fixture_route)
            fixture_page.route('**/api/design/**', fixture_route)
            fixture_context.add_init_script('localStorage.setItem("atelier-agent-session","browser-fixture-session");')
            fixture_page.goto(args.url + '/#studio', wait_until='domcontentloaded')
            fixture_page.wait_for_function('document.querySelector("#studio-session-label")?.textContent === "浏览器夹具：巴黎公寓"')
            fixture_page.locator('[data-studio-tab="preview"]').click()
            fixture_page.locator('#design-history [data-design-run]').click()
            fixture_page.locator('#visual-note').fill('隔离测试：正视图的窗套仍需修改。')
            fixture_page.get_by_role('button', name='保存视觉意见', exact=True).click()
            fixture_page.locator('#visual-status').filter(has_text='视觉意见已保存').wait_for()
            fixture_page.reload(wait_until='domcontentloaded')
            fixture_page.locator('[data-studio-tab="preview"]').click()
            fixture_page.locator('#design-history [data-design-run]').click()
            assert fixture_page.locator('#visual-note').input_value() == '隔离测试：正视图的窗套仍需修改。'
            assert fixture['review']['game_acceptance'] == 'PENDING'
            report['checks'].append('isolated_review_save_reload_restores_note_and_keeps_game_pending')
            fixture_page.locator('[data-delete-current]').click()
            fixture_page.locator('[data-undo-session]').wait_for()
            assert fixture_page.locator('#agent-sessions').inner_text() == '暂无会话'
            assert fixture_page.locator('#design-history [data-design-run]').count() == 1
            fixture_page.locator('[data-undo-session]').click()
            fixture_page.locator('#session-notice').filter(has_text='会话已恢复').wait_for()
            fixture_page.locator('[data-agent-session="' + fixture_session + '"]').wait_for()
            assert fixture_page.locator('#agent-session-select').input_value() == fixture_session
            assert fixture_page.locator('#design-history [data-design-run]').count() == 1
            report['checks'].append('isolated_delete_undo_reconciles_list_label_and_preserved_artifact')
            report['fixture_writes'] = fixture['writes']
            fixture_page.screenshot(path=str(args.out / 'isolated-restoration.png'), full_page=True)
            assert not report['page_errors'], report['page_errors']
            report['status'] = 'PASS'
        except Exception as error:
            report['status'] = 'FAIL'
            report['error'] = str(error)
            try:
                page.screenshot(path=str(args.out / 'failure.png'), full_page=True)
            except Exception:
                pass
        finally:
            browser.close()
            (args.out / 'continuation-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
