"""Final synthetic-page acceptance: facts, controls, immutable downloads, and geometry."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests'), str(ROOT / 'tests/training'), str(ROOT / 'tools')]
from health_change_browser import WRAPPER  # noqa: E402
from health_change_fixture import CUTOFF, create_health_change_fixture  # noqa: E402
from product_redesign_browser_check import geometry, settle  # noqa: E402
from product_redesign_fixture import create_product_fixture  # noqa: E402
from product_redesign_training_browser import RedesignCheck  # noqa: E402
from strength_workbench_browser_check import isolated_app, product_source_hashes  # noqa: E402

from healthzip.db.repository import Repository  # noqa: E402
from healthzip.workflows.period_report import load_report  # noqa: E402
from healthzip.workflows.report_objects import reconstruct_report  # noqa: E402

WIDTHS = (320, 375, 390, 430, 768, 1440)


def source_identity():
    names = [str(path.relative_to(ROOT)) for path in (ROOT/'src').rglob('*.py')]
    names += ['tools/repair_delivery_browser.py', 'tests/health_change_fixture.py', 'tests/product_redesign_fixture.py']
    return product_source_hashes(ROOT, extra=names)


class Check:
    def __init__(self, page, output, result):
        self.page, self.output, self.result = page, output, result

    def identity(self):
        return self.page.locator('[data-hz-render]').get_attribute('data-hz-render')

    def fresh(self, old):
        self.page.wait_for_function("old=>{const e=document.querySelector('[data-hz-render]');return e&&e.dataset.hzRender!==old}", arg=old, timeout=60000)
        settle(self.page)
        return self.identity()

    def text(self):
        assert not self.page.get_by_test_id('stException').count(), self.page.get_by_test_id('stException').all_text_contents()
        return self.page.get_by_test_id('stMain').inner_text()

    def radio(self, name):
        before = self.identity()
        item = self.page.get_by_role('radio', name=name, exact=True)
        if item.is_checked():
            return before
        item.locator('xpath=ancestor::label[1]').click()
        return self.fresh(before)

    def nav(self, name):
        if self.page.viewport_size['width'] > 900:
            return self.radio(name)
        before = self.identity()
        self.page.locator('.st-key-mobile_navigation button').first.click()
        popover = self.page.get_by_test_id('stPopoverBody')
        popover.wait_for(state='visible')
        popover.get_by_role('button', name=name, exact=True).click()
        popover.wait_for(state='hidden')
        return self.fresh(before)

    def click(self, name):
        before = self.identity()
        self.page.get_by_role('button', name=name, exact=True).click()
        return self.fresh(before)

    def select(self, label, option, *, full_rerun=True):
        before = self.identity()
        self.page.get_by_role('combobox', name=label, exact=True).click()
        self.page.get_by_role('option', name=option, exact=True).click()
        if full_rerun:
            return self.fresh(before)
        settle(self.page)
        return before

    def topic(self, name):
        self.page.get_by_role('button', name='切换主题或指标', exact=True).click()
        self.select('身体主题', name)
        self.page.keyboard.press('Escape')
        settle(self.page)

    def sleep_scope(self, name):
        self.page.get_by_role('button', name=re.compile('^睡眠口径 ·')).click()
        self.radio(name)
        self.page.keyboard.press('Escape')
        settle(self.page)

    def record(self, key, **details):
        self.result['checks'][key] = {'status': 'passed', 'render_id': self.identity(), **details}
        self.flush()
        print('PASS', key, flush=True)

    def flush(self):
        (self.output / 'browser.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2) + '\n')

    def capture(self, name, *, expected=(), chart=False):
        dimensions = {}
        for width in WIDTHS:
            self.page.set_viewport_size({'width': width, 'height': 1000 if width >= 768 else 844})
            self.page.wait_for_timeout(150)
            self.page.get_by_test_id('stMain').evaluate('e=>e.scrollTo(0,0)')
            self.page.wait_for_timeout(80)
            geom = geometry(self.page)
            assert geom['document'] <= geom['viewport'] and geom['main'] <= geom['main_client'], geom
            assert not geom['horizontal_overflow'], geom
            text = self.text()
            for wanted in expected:
                assert wanted in text, (name, width, wanted, text)
            metrics = self.page.locator('[data-testid="stMetricValue"],[data-testid="stMetricDelta"]').evaluate_all("els=>els.filter(e=>e.getClientRects().length&&(!e.closest('details')||e.closest('details').open)).map(e=>({text:e.innerText,width:e.clientWidth,scroll:e.scrollWidth,height:e.clientHeight,scrollHeight:e.scrollHeight,top:e.getBoundingClientRect().top,bottom:e.getBoundingClientRect().bottom}))")
            assert all(m['scroll'] <= m['width']+1 and m['scrollHeight'] <= m['height']+1 for m in metrics), metrics
            plots = self.page.get_by_test_id('stPlotlyChart')
            if chart:
                assert plots.count() > 0
            first_plot = plots.first.bounding_box() if plots.count() else None
            dimensions[str(width)] = {**geom, 'metrics': metrics, 'first_plot': first_plot,
                                      'first_plot_in_first_screen': bool(first_plot and first_plot['y'] < self.page.viewport_size['height'])}
            if width in (320, 390, 1440):
                self.page.screenshot(path=str(self.output / f'{name}-{width}.png'))
        self.page.set_viewport_size({'width': 1440, 'height': 1000})
        self.record(name, geometry=dimensions, rendered_text=self.text())
        (self.output / f'{name}.txt').write_text(self.text())


def add_second_source(path):
    """Append only synthetic ledger records, after unchanged-fixture captures."""
    repo = Repository(path)
    rows = repo.rows("SELECT record_id,available_at,payload_json FROM source_revision WHERE table_name='health_sample'")
    count = 0
    for item in rows:
        row = json.loads(item['payload_json'])
        if row.get('canonical_type') != 'resting_heart_rate_bpm':
            continue
        row.update(id=item['record_id'] + 100000, source_name='合成第二手表', device='second-synthetic-watch',
                   normalized_value=78.3755, raw_value='78.3755')
        repo.conn.execute("INSERT INTO source_revision(table_name,record_id,available_at,payload_json,temporal_provenance) VALUES('health_sample',?,?,?,'synthetic_delivery_source_switch')",
                          (row['id'], item['available_at'], json.dumps(row)))
        count += 1
    repo.conn.commit()
    repo.close()
    return count


def fixed(check, base, database):
    page = check.page
    page.goto(base + '/?workspace=overview')
    page.locator('[data-hz-render]').wait_for(state='attached', timeout=60000)
    settle(page)
    check.capture('overview', expected=('睡眠中位数', '6.0 小时'), chart=True)
    assert '平均睡眠' not in check.text()
    check.click('查看静息心率')
    check.radio('自定义')
    page.get_by_text('64.0 bpm', exact=True).first.wait_for(timeout=30000)
    check.capture('heart', expected=('64.0 bpm', '较前期 +5.0 bpm', '记录 7/7 天', '日代表值中位数', '30.0 ms'), chart=True)
    details = page.get_by_text(re.compile('^比较依据 · 日静息心率')).first
    details.click()
    assert '个人历史参考日静息心率' in check.text() and '59.0 bpm' in check.text()
    check.record('heart_reference_details', rendered_text=check.text())
    details.click()
    page.set_viewport_size({'width': 390, 'height': 844})
    check.radio('本月')
    monthly_id = check.identity()
    assert page.get_by_role('radio', name='本月', exact=True).is_checked()
    check.nav('总览')
    check.nav('身体')
    assert page.get_by_role('radio', name='本月', exact=True).is_checked()
    assert check.identity() != monthly_id
    check.record('return_retains_month', viewport=page.viewport_size, real_mobile_menu_clicks=['总览','身体'], rendered_text=check.text())
    page.set_viewport_size({'width': 1440, 'height': 1000})
    check.radio('自定义')
    check.topic('睡眠')
    check.capture('sleep', expected=('6.0 小时', '较前期 -2.0 小时', '记录 7/7 天', '日代表值中位数'), chart=True)
    page.set_viewport_size({'width': 390, 'height': 844})
    check.sleep_scope('截止前24小时')
    page.get_by_text('截止前24小时已记录睡眠 5.0 小时', exact=False).wait_for(timeout=30000)
    check.capture('sleep-24h', expected=('5.0 小时',), chart=True)
    check.sleep_scope('已声明主睡眠（冻结）')
    page.get_by_text('尚无此工作区已保存的主睡眠声明', exact=False).wait_for(timeout=30000)
    check.record('unknown_main_sleep_retains_other_scopes', rendered_text=check.text())
    check.sleep_scope('所选时期逐日总量')
    page.get_by_text('6.0 小时', exact=True).first.wait_for(timeout=30000)
    check.record('sleep_scope_restore', rendered_text=check.text())
    additions = add_second_source(database)
    check.topic('心率')
    check.select('记录来源', '合成第二手表')
    page.get_by_text('78.4 bpm', exact=True).first.wait_for(timeout=30000)
    assert '64.0 bpm' not in check.text()
    check.capture('source-filter', expected=('78.4 bpm', '合成第二手表'), chart=True)
    check.record('actual_source_filter', synthetic_added_rows=additions,
                 stored_raw_value=78.3755, displayed_value='78.4 bpm', rendered_text=check.text())
    check.select('记录来源', '合成手表')
    page.get_by_text('64.0 bpm', exact=True).first.wait_for(timeout=30000)
    assert '78.4 bpm' not in check.text()
    check.record('source_filter_return_original', rendered_text=check.text())
    check.select('记录来源', '全部来源（分别展示）')
    check.radio('复盘')
    check.radio('周月复盘')
    check.capture('report-preview', expected=('生成当前周期复盘',), chart=True)
    before = check.identity()
    started = time.perf_counter()
    page.get_by_role('button', name='生成当前周期复盘', exact=True).click()
    check.fresh(before)
    page.get_by_role('button', name='下载身体与力量联合报告', exact=True).wait_for(timeout=240000)
    settle(page)
    text = check.text()
    assert '完整本地复盘已保存' in text and '本期主要变化' in text and '下一步' in text
    with page.expect_download(timeout=30000) as task:
        page.get_by_role('button', name='下载身体与力量联合报告', exact=True).click()
    download = task.value
    markdown_file = check.output / 'downloaded-report.md'
    download.save_as(markdown_file)
    markdown = markdown_file.read_text()
    assert '本期主要变化' in markdown and '下一步' in markdown
    with sqlite3.connect(database) as conn:
        row = conn.execute('SELECT report_id,markdown FROM joint_period_report ORDER BY created_at DESC LIMIT 1').fetchone()
    assert row and markdown == row[1]
    check.record('report_download_actual_frozen_bytes', report_id=row[0], bytes=markdown_file.stat().st_size,
                 elapsed_seconds=time.perf_counter()-started, sha256=hashlib.sha256(markdown_file.read_bytes()).hexdigest())
    check.capture('report-completed', expected=('完整本地复盘已保存', '本期主要变化', '下一步'), chart=True)
    page.get_by_text('按问题查看冻结记录与依据', exact=True).first.click()
    previous_fact = page.get_by_text(re.compile('^事实身份：question:')).inner_text()
    check.select('冻结问题', '睡眠时长与随后同条件 SDNN 有怎样的关系？', full_rerun=False)
    page.wait_for_function("old=>[...document.querySelectorAll('[data-testid=stCaptionContainer]')].some(e=>e.innerText.startsWith('事实身份：question:')&&e.innerText!==old)", arg=previous_fact, timeout=30000)
    page.get_by_text(re.compile('^事实身份：question:')).wait_for(timeout=30000)
    fact_text = page.get_by_text(re.compile('^事实身份：question:')).inner_text()
    check.record('report_frozen_question_actual_click', fact_text=fact_text, rendered_text=check.text())
    check.capture('report-question-detail', expected=('事实身份：question:', '冻结问题'))
    page.get_by_role('button', name='准备完整审计包', exact=True).first.click()
    page.get_by_role('button', name='下载完整审计包', exact=True).first.wait_for(timeout=30000)
    with page.expect_download(timeout=30000) as task:
        page.get_by_role('button', name='下载完整审计包', exact=True).first.click()
    audit_file = check.output / 'downloaded-frozen-audit.json'
    task.value.save_as(audit_file)
    bundle = json.loads(audit_file.read_text())
    assert bundle['format'] == 'healthzip-frozen-audit-2' and bundle['content_objects'] and bundle['analysis_objects']
    rebuilt = reconstruct_report(bundle)
    assert rebuilt['markdown'] == markdown and rebuilt['report_id'] == row[0]
    q6 = next(q for q in rebuilt['questions'] if q['id'] == 'W6')
    assert q6['fact_id'] in fact_text
    assert q6['association']['groups'][0]['pairs']
    repo = Repository(database)
    frozen = load_report(repo, row[0])
    assert frozen['questions'] == rebuilt['questions']
    repo.close()
    check.record('audit_download_offline_reconstruction', report_id=rebuilt['report_id'], bytes=audit_file.stat().st_size,
                 manifest_format=bundle['report_manifest']['storage_format'], objects=len(bundle['content_objects']),
                 analysis_objects=len(bundle['analysis_objects']), question_fact_id=q6['fact_id'], matched_frozen_questions=True)
    check.radio('问题分析')
    check.select('想了解的问题', '所选期间的可比表现和身体轨迹如何？')
    assert '条件尚不能唯一对齐' in check.text()
    check.capture('missing-training-conditions', expected=('条件尚不能唯一对齐', '下一步'))
    check.radio('训练')
    training = RedesignCheck(page, database, check.output)
    training.wait(lambda: training.testid('strength-home').is_visible(), timeout=60000)
    check.capture('training-home-main')
    training.click('open-start')
    training.choose('卧推', 'psa.ex.barbell_bench_press')
    session = training.active()
    actual = session['exercises'][0]['sets'][0]['set_uuid']
    training.fill_row(actual, load='32.5', quantity='8', rir='0')
    check.capture('training-input-main')
    assert training.row(actual).locator('[data-field="load_value"]').input_value() == '32.5'
    assert training.row(actual).locator('[data-field="reps"]').input_value() == '8'
    assert training.row(actual).locator('[data-field="rir"]').input_value() == '0'
    check.record('training_input_retained_after_six_main_viewports', load='32.5', reps='8', rir='0')


def sparse(check, base, mode):
    page = check.page
    for route in ('overview', 'heart', 'sleep', 'weight', 'cardio', 'workouts'):
        page.goto(base + '/?workspace=' + route)
        page.locator('[data-hz-render]').wait_for(state='attached', timeout=60000)
        settle(page)
        text = check.text()
        assert 'Traceback' not in text
        if mode == 'empty' and route in {'heart', 'sleep', 'weight', 'cardio'}:
            assert page.get_by_test_id('stMetric').count() == 0
        if mode == 'single' and route == 'heart':
            assert '60.0 bpm' in text
        check.capture(mode+'-'+route)
    check.radio('复盘')
    check.radio('问题分析')
    check.select('想了解的问题', '睡眠时长与随后同条件 SDNN 有怎样的关系？')
    check.capture(mode+'-w6', expected=('下一步',))


def metric_arrows(check, base):
    """Verify signs in both body renderers, without inferred arrow direction."""
    page = check.page
    page.goto(base + '/?workspace=overview')
    page.locator('[data-hz-render]').wait_for(state='attached', timeout=60000)
    settle(page)
    check.click('查看静息心率')
    check.radio('自定义')
    for topic, expected in [('心率', ('64.0 bpm', '较前期 +5.0 bpm')),
                            ('睡眠', ('6.0 小时', '较前期 -2.0 小时'))]:
        if topic == '睡眠':
            check.topic(topic)
        check.capture('neutral-arrows-' + topic, expected=expected, chart=True)
        assert not page.locator('[data-testid^="stMetricDeltaIcon-"]').count()
        check.record('no-inferred-arrow-' + topic, deltas=page.get_by_test_id('stMetricDelta').all_text_contents())
    check.topic('心率')
    page.get_by_role('button', name='切换主题或指标', exact=True).click()
    check.select('查看指标', '日静息心率')
    page.keyboard.press('Escape')
    settle(page)
    check.capture('neutral-arrows-individual-metric', expected=('64.0 bpm', '较前期 +5.0 bpm'), chart=True)
    assert not page.locator('[data-testid^="stMetricDeltaIcon-"]').count()
    check.record('no-inferred-arrow-individual-metric', deltas=page.get_by_test_id('stMetricDelta').all_text_contents())


def run(output, mode, concurrent_load):
    output.mkdir(parents=True, exist_ok=True)
    result = {'data': 'synthetic_only', 'mode': mode, 'checks': {}, 'errors': [], 'external_model_calls': 0,
              'physical_iphone_safari_soft_keyboard': 'not_verified', 'source_before': source_identity(),
              'concurrent_load': concurrent_load, 'timing_scope': 'functional interaction receipt, not performance acceptance'}
    with tempfile.TemporaryDirectory(prefix='hz-repair-delivery-') as tmp:
        folder = Path(tmp)
        database = folder / '.local/healthzip.sqlite3'
        database.parent.mkdir(parents=True)
        fixed_fixture = mode in {'fixed', 'metric-arrows'}
        result['fixture'] = create_health_change_fixture(database) if fixed_fixture else create_product_fixture(database, mode=mode)
        code = ROOT
        if fixed_fixture:
            code = folder / 'wrapper'
            code.mkdir()
            (code/'src').symlink_to(ROOT/'src', target_is_directory=True)
            (code/'.streamlit').symlink_to(ROOT/'.streamlit', target_is_directory=True)
            (code/'app.py').write_text(WRAPPER.format(cutoff=CUTOFF, app=str(ROOT/'app.py')))
        with isolated_app(code, folder) as base, sync_playwright() as engine:
            browser = engine.chromium.launch(headless=True, args=['--no-sandbox'])
            result['browser'] = browser.version
            page = browser.new_page(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
            page.route('http**/*', lambda route: route.continue_() if route.request.url.startswith(base+'/') else route.abort())
            page.on('pageerror', lambda error: result['errors'].append(str(error)))
            check = Check(page, output, result)
            try:
                if mode == 'fixed':
                    fixed(check, base, database)
                elif mode == 'metric-arrows':
                    metric_arrows(check, base)
                else:
                    sparse(check, base, mode)
                assert not result['errors'], result['errors']
                result['status'] = 'passed'
            except Exception as exc:
                result.update(status='failed', failure=str(exc))
                page.screenshot(path=str(output/'failure.png'))
                (output/'failure.txt').write_text(page.get_by_test_id('stMain').inner_text())
                raise
            finally:
                result['source_after'] = source_identity()
                result['source_identity_unchanged'] = result['source_before'] == result['source_after']
                check.flush()
                browser.close()
    print(json.dumps({'status': result['status'], 'checks': len(result['checks']), 'source_identity_unchanged': result['source_identity_unchanged']}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=('fixed', 'empty', 'single', 'old', 'metric-arrows'), default='fixed')
    parser.add_argument('--concurrent-load', default='Other host load not measured')
    args = parser.parse_args()
    run(args.output.resolve(), args.mode, args.concurrent_load)
