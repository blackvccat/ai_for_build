"""Browser smoke check against the running local workbench, with screenshots."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8765')
    parser.add_argument('--out', type=Path, default=ROOT / 'runs/LEARNING-WORKBENCH-v1/browser')
    args = parser.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1100}, device_scale_factor=1)
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(args.url, wait_until='networkidle')
        page.get_by_role('heading', name='从优秀建筑中学习，让创新有据可循。').wait_for()
        page.screenshot(path=str(out / 'overview.png'), full_page=True)
        page.locator('nav a[data-page=library]').click()
        page.locator('.knowledge-card').first.wait_for()
        page.locator('[data-layer=technique]').click()
        page.locator('#search-input').fill('屋顶上排烟的烟囱')
        page.get_by_role('button', name='检索知识').click()
        page.wait_for_function("document.querySelector('.knowledge-card h3')?.textContent === '烟囱'")
        page.screenshot(path=str(out / 'search.png'), full_page=True)
        page.locator('.knowledge-card').first.click()
        page.get_by_role('heading', name='来源证据', exact=True).wait_for()
        page.screenshot(path=str(out / 'evidence.png'), full_page=True)
        page.get_by_role('button', name='关闭知识详情').click()
        page.locator('nav a[data-page=studio]').click()
        page.locator('[data-studio-tab=preview]').click()
        page.locator('.manual-research > summary').click()
        page.locator('#brief-local').click()
        page.get_by_role('heading', name='四层检索依据').wait_for(timeout=30000)
        assert page.locator('#brief-results .panel').count() == 4
        page.screenshot(path=str(out / 'studio.png'), full_page=True)
        page.goto(args.url.rstrip('/') + '/#audit', wait_until='networkidle')
        page.locator('.exclusion').first.wait_for()
        page.screenshot(path=str(out / 'audit.png'), full_page=True)
        page.locator('nav a[data-page=sources]').click()
        page.locator('.source-card img').first.wait_for()
        page.wait_for_load_state('networkidle')
        assert page.locator('.source-card').count() == 14
        page.set_viewport_size({'width': 390, 'height': 844})
        page.locator('nav a[data-page=overview]').click()
        page.wait_for_load_state('networkidle')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile horizontal overflow'
        page.screenshot(path=str(out / 'mobile.png'), full_page=True)
        browser.close()
    report = {'status': 'PASS' if not errors else 'FAIL', 'page_errors': errors,
              'checks': ['overview', 'semantic_search', 'evidence_drawer', 'four_layer_brief',
                         'exclusion_browser', '14_source_images', 'mobile_no_horizontal_overflow']}
    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    assert not errors, errors

if __name__ == '__main__': main()
