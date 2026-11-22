"""Open a measured field in the real application and inspect its current original sources."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests'), str(ROOT/'tests/training'), str(ROOT/'tools')]
from health_change_browser import WRAPPER  # noqa: E402
from master_science_fixture import CUTOFF, create_master_science_fixture  # noqa: E402
from product_redesign_browser_check import settle  # noqa: E402
from strength_workbench_browser_check import isolated_app  # noqa: E402


def run(output, browser_executable=None):
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='hz-synthetic-method-browser-') as temp:
        folder = Path(temp)
        fixture = create_master_science_fixture(folder / '.local/healthzip.sqlite3', include_training=False)
        dest = folder/'.local/knowledge'
        dest.mkdir()
        for name in ('sources.sqlite3','theories.sqlite3'):
            with sqlite3.connect((ROOT/'.local/knowledge'/name).as_uri() + '?mode=ro', uri=True) as source, sqlite3.connect(dest/name) as target:
                source.backup(target)
        wrapper = folder/'wrapper'
        wrapper.mkdir()
        (wrapper/'src').symlink_to(ROOT/'src', target_is_directory=True)
        (wrapper/'.streamlit').symlink_to(ROOT/'.streamlit', target_is_directory=True)
        (wrapper/'app.py').write_text(WRAPPER.format(cutoff=CUTOFF, app=str(ROOT/'app.py')))
        with isolated_app(wrapper, folder) as base, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--no-sandbox'], executable_path=browser_executable)
            page = browser.new_page(viewport={'width':1440,'height':1000})
            page.route('http**/*',lambda route: route.continue_() if route.request.url.startswith(base+'/') else route.abort())
            page.goto(base+'/?workspace=environment')
            page.locator('[data-hz-render]').wait_for(state='attached', timeout=60000)
            settle(page)
            page.get_by_role('button',name='切换主题或指标',exact=True).click()
            page.get_by_role('combobox',name='查看指标').click()
            page.get_by_role('option',name='环境声音暴露').click()
            settle(page)
            page.keyboard.press('Escape')
            page.get_by_text('依据与原文',exact=True).click()
            page.get_by_role('button',name='查阅本题依据').click()
            source = page.get_by_role('link',name='Understand Noise Exposure',exact=False).first
            source.wait_for(timeout=30000)
            settle(page)
            docs = page.get_by_role('link',name='Apple 字段定义',exact=False).first
            assert docs.is_visible()
            assert 'cdc.gov/niosh' in source.get_attribute('href')
            assert 'environmentalaudioexposure' in docs.get_attribute('href')
            assert page.get_by_text('dB表达的是对数关系',exact=False).first.is_visible()
            energy = page.get_by_role('link', name='Criteria for a Recommended Standard', exact=False).first
            assert 'stacks.cdc.gov/view/cdc/6376' in energy.get_attribute('href')
            checks = {'original_source':source.get_attribute('href'),'official_field':docs.get_attribute('href'),
                      'energy_original':energy.get_attribute('href'),
                      'browser':browser.version,'source_paragraph_displayed':True,'synthetic_fixture':fixture}
            checks['plot_axes'] = page.locator('.js-plotly-plot').evaluate_all(
                "els => els.map(el => ({tickmode:el.layout?.xaxis?.tickmode,ticktext:el.layout?.xaxis?.ticktext}))")
            assert any(axis.get('tickmode') == 'array' and axis.get('ticktext')
                       for axis in checks['plot_axes'])
            for width,height in ((1440,1000),(390,844)):
                page.set_viewport_size({'width':width,'height':height})
                source.scroll_into_view_if_needed()
                page.screenshot(path=str(output/f'environmental-source-{width}.png'))
                energy.scroll_into_view_if_needed()
                page.screenshot(path=str(output/f'environmental-energy-source-{width}.png'))
            (output/'browser.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n')
            browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/master_redesign/knowledge/browser')
    parser.add_argument('--browser-executable')
    args = parser.parse_args()
    run(args.output, args.browser_executable)
