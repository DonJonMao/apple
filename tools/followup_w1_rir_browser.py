"""Real W1 page/report with synthetic ordinary sets and the actual public library."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests'), str(ROOT / 'tests/training'), str(ROOT / 'tools')]
from health_change_browser import WRAPPER  # noqa: E402
from product_redesign_browser_check import geometry, settle  # noqa: E402
from repair_delivery_browser import Check  # noqa: E402
from strength_workbench_browser_check import isolated_app  # noqa: E402

from healthzip.db.repository import Repository  # noqa: E402
from healthzip.workflows.period_report import load_report  # noqa: E402
from healthzip.workflows.report_objects import audit_bundle, reconstruct_report  # noqa: E402
from tests.knowledge.test_w1_computed_rir_scope import completed_sets  # noqa: E402

CUTOFF = '2025-04-13T20:00:00+08:00'
DEFINITION = 'Halperin等2021作者预印本把RIR用于描述'
METHOD = '该2021作者预印本纳入无已知疾病或损伤人群'


def run(knowledge, output, chromium=None):
    output.mkdir(parents=True, exist_ok=False)
    result = {'data': 'synthetic_only', 'knowledge': str(knowledge), 'external_calls': 0,
        'physical_iPhone_Safari': 'not_verified', 'checks': {}, 'errors': [],
        'source_hashes': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in [ROOT / 'app.py', *(ROOT / 'src/healthzip').rglob('*.py')]}}
    (output / 'browser.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=['--no-sandbox'], executable_path=chromium)
        result['browser'] = browser.version
        for scenario, actuals in [('direct', [{'rir': 2}, {'rir': 1}, {'rir': 0}]),
                                 ('mixed', [{'rir': 2}, {'rir': 1}, {}])]:
            with tempfile.TemporaryDirectory(prefix='hz-w1-rir-browser-') as temp:
                folder = Path(temp)
                database = folder / '.local/healthzip.sqlite3'
                database.parent.mkdir()
                repo = Repository(database)
                completed_sets(repo, actuals)
                repo.close()
                (folder / '.local/knowledge').symlink_to(knowledge, target_is_directory=True)
                wrapper = folder / 'wrapper'
                wrapper.mkdir()
                (wrapper / 'src').symlink_to(ROOT / 'src', target_is_directory=True)
                (wrapper / '.streamlit').symlink_to(ROOT / '.streamlit', target_is_directory=True)
                code = WRAPPER.format(cutoff=CUTOFF, app=str(ROOT / 'app.py'))
                code = code.replace('"body_period", "自定义"', '"body_period", "近30天"')
                code = code.replace('"analysis_window_days", 7', '"analysis_window_days", 30')
                (wrapper / 'app.py').write_text(code)
                with isolated_app(wrapper, folder) as base:
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                    page.route('http**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
                    page.on('pageerror', lambda exc: result['errors'].append(str(exc)))
                    check = Check(page, output, result)
                    page.goto(base + '/?workspace=review')
                    page.locator('[data-hz-render]').wait_for(state='attached', timeout=60000)
                    settle(page)
                    check.radio('问题分析')
                    assert '同动作完成表现' in check.text()
                    assert '3 条实际记录' in check.text()

                    def sources():
                        summary = page.get_by_text('依据与原文', exact=True).last
                        details = summary.locator('xpath=ancestor::details[1]')
                        if not details.evaluate('e=>e.open'):
                            summary.click()
                        check.click('查阅本题依据')
                        page.get_by_role('link').filter(has_text='Repetitions').first.wait_for(timeout=45000)
                        return check.text()

                    text = sources()
                    assert (DEFINITION in text) is (scenario == 'direct')
                    assert (METHOD in text) is (scenario == 'direct')
                    dimensions = {}
                    focus = DEFINITION if scenario == 'direct' else '依据与原文'
                    for width in (320, 375, 390, 430, 768, 1440):
                        page.set_viewport_size({'width': width, 'height': 844 if width < 768 else 1000})
                        page.get_by_text(focus, exact=False).first.scroll_into_view_if_needed()
                        settle(page)
                        dim = geometry(page)
                        assert dim['document'] <= dim['viewport'] and dim['main'] <= dim['main_client'], dim
                        dimensions[str(width)] = dim
                        page.screenshot(path=str(output / f'{scenario}-{width}.png'))
                    (output / f'{scenario}-page.txt').write_text(text)
                    check.record(scenario + '-real-page', direct_rir_explanation=scenario == 'direct',
                                 geometry=dimensions, actual_set_count=3)
                    page.set_viewport_size({'width': 1440, 'height': 1000})
                    before_fact = page.locator('[data-hz-question]').get_attribute('data-hz-question')
                    check.radio('本周')
                    after_fact = page.locator('[data-hz-question]').get_attribute('data-hz-question')
                    assert before_fact != after_fact and DEFINITION not in check.text()
                    refreshed = sources()
                    assert (DEFINITION in refreshed) is (scenario == 'direct')
                    check.record(scenario + '-scope-cache', before_fact=before_fact, after_fact=after_fact,
                                 old_evidence_cleared=True, new_evidence_checked=True)
                    if scenario == 'direct':
                        check.radio('周月复盘')
                        check.click('生成当前周期复盘')
                        page.get_by_role('button', name='下载身体与力量联合报告', exact=True).wait_for(timeout=60000)
                        with page.expect_download() as downloaded:
                            page.get_by_role('button', name='下载身体与力量联合报告', exact=True).click()
                        downloaded.value.save_as(output / 'report.md')
                        body = (output / 'report.md').read_text()
                        repo = Repository(database)
                        identity = repo.one('SELECT report_id FROM joint_period_report ORDER BY rowid DESC LIMIT 1')[0]
                        report = load_report(repo, identity, include_details=True)
                        q = next(q for q in report['questions'] if q['id'] == 'W1')
                        items = [i for i in q['evidence']['items'] if 'RIR-PREPRINT' in i['claim_id']]
                        assert len(items) == 2 and body == report['markdown']
                        for item in items:
                            assert item['statement'] in body
                            assert all(limit in body for limit in item['limitations'])
                            assert all(c['url'] in body for c in item['citations'])
                        assert q['evidence']['applicability_context']['metric_evidence']['direct_rir_only']
                        assert reconstruct_report(audit_bundle(repo, identity)) == report
                        check.record('real-report-freeze-download', report_id=identity, fact_id=q['fact_id'],
                            analysis_version=q['analysis_version'], claims=[i['claim_id'] for i in items],
                            evidence_context=q['evidence']['applicability_context'],
                            provenance_records=len(q['evidence_observations']['training_sets']),
                            body_bytes=len(body.encode()), all_limits_and_citations_present=True, audit_reconstructed=True)
                        repo.close()
                        page.screenshot(path=str(output / 'report-1440.png'))
                    page.close()
        browser.close()
    result['source_hashes_after'] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                     for name in result['source_hashes']}
    result['source_unchanged_during_run'] = result['source_hashes'] == result['source_hashes_after']
    assert result['source_unchanged_during_run']
    (output / 'browser.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--knowledge', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--chromium')
    args = parser.parse_args()
    try:
        run(args.knowledge.resolve(), args.output.resolve(), args.chromium)
    except Exception:
        (args.output / 'failure.txt').write_text(traceback.format_exc())
        raise
