"""Read restored action evidence in the real app on a synthetic health workspace."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests'), str(ROOT / 'tests/training'), str(ROOT / 'tools')]
from health_change_browser import WRAPPER  # noqa: E402
from master_science_fixture import CUTOFF, create_master_science_fixture  # noqa: E402
from product_redesign_browser_check import geometry, settle  # noqa: E402
from strength_workbench_browser_check import isolated_app  # noqa: E402


def run(output, knowledge):
    output.mkdir(parents=True, exist_ok=True)
    result = {'data': 'synthetic_health_and_public_knowledge_backup', 'external_model_calls': 0,
              'physical_iPhone_Safari_keyboard': 'not_verified', 'checks': [], 'errors': [],
              'source_hashes': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
                  'src/healthzip/knowledge/topics.py', 'src/healthzip/knowledge/metric_retrieval.py',
                  'src/healthzip/ui/topic_sources.py')}}
    with TemporaryDirectory(prefix='hz-repair-rag-browser-') as temp:
        folder = Path(temp)
        result['fixture'] = create_master_science_fixture(folder / '.local/healthzip.sqlite3', include_training=False)
        dest = folder / '.local/knowledge'
        dest.mkdir()
        for name in ('sources.sqlite3', 'theories.sqlite3'):
            with sqlite3.connect((knowledge / name).as_uri() + '?mode=ro', uri=True) as source, sqlite3.connect(dest / name) as target:
                source.backup(target)
        wrapper = folder / 'wrapper'
        wrapper.mkdir()
        (wrapper / 'src').symlink_to(ROOT / 'src', target_is_directory=True)
        (wrapper / '.streamlit').symlink_to(ROOT / '.streamlit', target_is_directory=True)
        (wrapper / 'app.py').write_text(WRAPPER.format(cutoff=CUTOFF, app=str(ROOT / 'app.py')))
        with isolated_app(wrapper, folder) as base, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
            result['browser'] = browser.version
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.route('http**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
            page.on('pageerror', lambda exc: result['errors'].append(str(exc)))
            page.goto(base + '/?workspace=night')
            page.locator('[data-hz-render]').wait_for(state='attached', timeout=60000)
            settle(page)
            page.get_by_role('button', name='切换主题或指标', exact=True).click()
            page.get_by_role('combobox', name='查看指标').click()
            page.get_by_role('option', name='血氧饱和度', exact=True).click()
            settle(page)
            page.keyboard.press('Escape')
            page.get_by_text('依据与原文', exact=True).click()
            page.get_by_role('button', name='查阅本题依据').click()
            action = page.get_by_text('核对血氧读数时同时记录日期、时间和实际症状', exact=False).first
            action.wait_for(timeout=45000)
            action.scroll_into_view_if_needed()
            settle(page)
            assert page.get_by_text('FDA说明涉及脉搏血氧仪，指夹测量的误差不能移用到手腕。', exact=False).first.is_visible()
            assert page.get_by_text('不由手表单点读数诊断低氧', exact=False).first.count() == 1
            assert page.get_by_test_id('stException').count() == 0
            links = page.get_by_role('link', name='Pulse Oximeter Basics', exact=False)
            assert links.count() >= 1
            assert 'fda.gov' in links.first.get_attribute('href')
            result['checks'].append({'name': 'oxygen_method_and_restored_action', 'passed': True,
                'source': links.first.get_attribute('href'), 'actual_action': action.inner_text(),
                'complete_scope_limits_retained': True})
            scope = page.get_by_text('这条说明的适用范围', exact=True).last
            scope.click()
            assert page.get_by_text('Public consumer follow-up guidance', exact=False).first.is_visible()
            dimensions = {}
            for width in (320, 375, 390, 430, 768, 1440):
                page.set_viewport_size({'width': width, 'height': 1000 if width >= 768 else 844})
                action.scroll_into_view_if_needed()
                page.wait_for_timeout(120)
                dimensions[str(width)] = geometry(page)
                dim = dimensions[str(width)]
                assert dim['document'] <= dim['viewport'] and dim['main'] <= dim['main_client'], dim
                if width in (390, 1440):
                    page.screenshot(path=str(output / f'oxygen-action-{width}.png'))
            result['checks'].append({'name': 'source_action_six_widths', 'passed': True, 'geometry': dimensions})
            result['rendered_body'] = page.get_by_test_id('stMain').inner_text()
            (output / 'browser.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
            browser.close()
    print(json.dumps({'checks': len(result['checks']), 'errors': result['errors']}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/repair_knowledge/browser')
    parser.add_argument('--knowledge', type=Path, required=True)
    args = parser.parse_args()
    run(args.output, args.knowledge.resolve())
