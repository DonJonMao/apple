"""Synthetic real-page evidence for neutral associations and ordinary progress."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests'), str(ROOT / 'tests/training'), str(ROOT / 'tools')]
from health_change_browser import WRAPPER  # noqa: E402
from master_science_fixture import CUTOFF, create_master_science_fixture  # noqa: E402
from product_redesign_browser_check import geometry, settle  # noqa: E402
from strength_workbench_browser_check import isolated_app, product_source_hashes  # noqa: E402

from healthzip.db.repository import Repository  # noqa: E402
from healthzip.training.semantics import timestamp  # noqa: E402
from healthzip.training.service import TrainingService  # noqa: E402


def fixture(path):
    receipt = create_master_science_fixture(path)
    repo = Repository(path)
    originals = repo.rows("SELECT record_id,available_at,payload_json FROM source_revision WHERE table_name='health_sample'")
    for item in originals:
        row = json.loads(item['payload_json'])
        if row.get('source_name') != '合成长时段手表' or row.get('canonical_type') not in {'sleep_stage', 'hrv_sdnn_ms'}:
            continue
        row.update(id=int(item['record_id'])+3000000, source_name='合成负关联手表', device='独立负向设备')
        if row['canonical_type'] == 'hrv_sdnn_ms':
            row['value'] = 80 - float(row.get('normalized_value', row.get('value', row.get('raw_value'))))
            row['normalized_value'] = row['value']
            row['raw_value'] = str(row['value'])
        repo.conn.execute("INSERT INTO source_revision(table_name,record_id,available_at,payload_json,temporal_provenance) VALUES('health_sample',?,?,?,'synthetic_acceptance')",
                          (row['id'], item['available_at'], json.dumps(row, ensure_ascii=False)))
    repo.conn.commit()
    service = TrainingService(repo)
    rack = service.create_equipment('三次普通记录专用架', 'barbell')
    exercise = service.create_exercise('合成普通三次记录', 'repetitions', 'barbell', 'external_total_kg', exercise_id='custom.repair.ordinary')
    condition = {'equipment_instance_id': rack['id'], 'load_basis': 'external_total_kg', 'load_basis_confirmed': True,
                 'side': 'bilateral', 'repetition_semantics': 'full_repetitions', 'rom_protocol': 'full', 'settings': {}, 'settings_confirmed': True}
    for day, reps in ((4, 10), (11, 11), (19, 12)):
        at = f'2026-11-{day:02d}T17:00:00+08:00'
        with patch('healthzip.training.service.timestamp', side_effect=lambda value=None: timestamp(value) if value else at):
            session = service.start_session('合成普通进展验收', started_at=at)
            instance = service.add_exercise(session['id'], exercise['exercise_id'], condition)
            service.add_set(instance['id'], actual={'completion_state': 'completed', 'set_type': 'work', 'load_value': 30,
                'load_unit': 'kg', 'reps': reps, 'rir': None if reps == 11 else 0, 'ended_at': at})
            service.end_session(session['id'], ended_at=at)
    repo.close()
    return {**receipt, 'additional_association': 'negative_source_reflected_about_40_ms', 'ordinary_reps': [10,11,12],
            'ordinary_load_kg': 30, 'reference_set': False}


def run(output, code, baseline):
    output.mkdir(parents=True, exist_ok=True)
    result = {'data':'synthetic_only', 'mode':'before' if baseline else 'after', 'checks': {}, 'errors': [],
              'external_model_calls':0, 'device':'headless Chromium; no physical iPhone/Safari/keyboard validation'}
    with tempfile.TemporaryDirectory(prefix='hz-repair-science-') as tmp:
        folder = Path(tmp)
        database = folder / '.local/healthzip.sqlite3'
        if baseline:
            command = ("import sys,json;sys.path[:0]=" + repr([str(code/'src'), str(ROOT)]) + ";"
                       "from tools.repair_science_browser import fixture;"
                       "print(json.dumps(fixture(" + repr(str(database)) + "),ensure_ascii=False))")
            result['fixture'] = json.loads(subprocess.check_output([sys.executable, '-c', command], text=True))
        else:
            result['fixture'] = fixture(database)
        result['source_identity'] = product_source_hashes(code)
        wrapper = folder / 'wrapper'
        wrapper.mkdir()
        (wrapper/'src').symlink_to(code/'src', target_is_directory=True)
        (wrapper/'.streamlit').symlink_to(code/'.streamlit', target_is_directory=True)
        script = WRAPPER.format(cutoff=CUTOFF, app=str(code/'app.py'))
        script = script.replace('st.session_state.setdefault("analysis_window_days", 7)', 'st.session_state.setdefault("analysis_window_days", 365)')
        (wrapper/'app.py').write_text(script)
        with isolated_app(wrapper, folder) as base, sync_playwright() as engine:
            browser = engine.chromium.launch(headless=True, args=['--no-sandbox'])
            result['browser'] = browser.version
            page = browser.new_page(viewport={'width':1440,'height':1000})
            page.route('http**/*', lambda route: route.continue_() if route.request.url.startswith(base+'/') else route.abort())
            page.on('pageerror', lambda exc: result['errors'].append(str(exc)))
            def check_text():
                assert page.get_by_test_id('stException').count() == 0, page.get_by_test_id('stException').all_text_contents()
                return page.get_by_test_id('stMain').inner_text()
            def radio(name):
                page.get_by_role('radio',name=name,exact=True).locator('xpath=ancestor::label[1]').click()
                settle(page)
            def select(label, option):
                page.get_by_role('combobox',name=label,exact=True).click()
                page.get_by_role('option',name=option,exact=True).click()
                settle(page)
            def capture(name):
                dims={}
                for width in (320,375,390,430,768,1440):
                    page.set_viewport_size({'width':width,'height':1000 if width>=768 else 844})
                    page.wait_for_timeout(120)
                    page.get_by_test_id('stMain').evaluate('el=>el.scrollTo(0,0)')
                    dims[str(width)] = geometry(page)
                    assert not dims[str(width)]['horizontal_overflow'], dims[str(width)]
                    if width in (390,1440):
                        page.screenshot(path=str(output/f'{name}-{width}.png'),full_page=True)
                result['checks'][name] = {'geometry':dims,'rendered_text':check_text()}
                (output/'browser.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
            try:
                page.goto(base+'/?workspace=review')
                page.locator('[data-hz-render]').wait_for(state='attached',timeout=60000)
                settle(page)
                radio('复盘')
                radio('问题分析')
                select('想了解的问题','睡眠时长与随后同条件 SDNN 有怎样的关系？')
                page.get_by_text('估计关联' if baseline else '观察性条件关联',exact=False).first.wait_for(timeout=60000)
                text=check_text()
                assert '区间' in text and page.get_by_test_id('stPlotlyChart').count()>=2
                if not baseline:
                    assert '合成负关联手表' in text and '合成长时段手表' in text
                    assert '本组暂不能估计条件关联' in text and '实际采样' in text
                    assert '支持这项解释的记录' not in text and '削弱这项解释的记录' not in text
                    assert '未扣除时间等因素' in text
                    page.get_by_text('本组配对日期与适用性 1',exact=True).click()
                    assert '相邻记录的实际变化' in check_text()
                    page.get_by_text('本组配对日期与适用性 1',exact=True).click()
                capture('w6-groups')
                plots=page.locator('.js-plotly-plot').evaluate_all('els=>els.map(el=>el.data?.map(t=>({x:t.x,y:t.y})))')
                result['checks']['w6-groups']['plots']=plots
                if not baseline:
                    old_identity=page.locator('[data-hz-question]').get_attribute('data-hz-question')
                    page.get_by_role('button',name='记录来源',exact=True).click()
                    select('记录来源','合成负关联手表')
                    page.keyboard.press('Escape')
                    page.wait_for_function("old=>document.querySelector('[data-hz-question]')?.getAttribute('data-hz-question')!==old",arg=old_identity,timeout=60000)
                    page.get_by_text('观察性条件关联 +2.92',exact=False).wait_for(state='detached',timeout=60000)
                    page.get_by_text('观察性条件关联 -2.92',exact=False).wait_for(timeout=60000)
                    filtered=check_text()
                    assert '观察性条件关联 +2.92' not in filtered and '本组暂不能估计条件关联' not in filtered
                    assert page.get_by_test_id('stPlotlyChart').count()==1
                    result['checks']['source_switch_negative_only']={'status':'passed','rendered_text':filtered,
                        'previous_fact_id':old_identity,'fact_id':page.locator('[data-hz-question]').get_attribute('data-hz-question')}
                    page.get_by_role('button',name='记录来源',exact=True).click()
                    select('记录来源','全部来源（分别展示）')
                    page.keyboard.press('Escape')
                    page.get_by_text('观察性条件关联 +2.92',exact=False).wait_for(timeout=60000)
                select('想了解的问题','所选期间的可比表现和身体轨迹如何？')
                if not baseline:
                    page.get_by_text('普通训练的完整轨迹与阶段对照',exact=False).first.click()
                    page.get_by_role('combobox',name='动作、条件与组位',exact=True).click()
                    page.get_by_role('option',name='合成普通三次记录',exact=False).first.click()
                    settle(page)
                    assert '3 条实际记录' in check_text() and '30 kg × 10 次' in check_text() and '30 kg × 12 次' in check_text()
                    charts=page.locator('.js-plotly-plot').evaluate_all('els=>els.map(el=>el.data?.map(t=>({x:t.x,y:t.y})))')
                    assert any(trace.get('y')==[10,11,12] for chart in charts if chart for trace in chart),charts
                    result['ordinary_plots']=charts
                capture('ordinary-training')
                assert not result['errors'],result['errors']
                result['status']='passed'
            except Exception as exc:
                result['status']='failed'
                result['failure']=str(exc)
                page.screenshot(path=str(output/'failure.png'),full_page=True)
                (output/'failure-text.txt').write_text(page.get_by_test_id('stMain').inner_text())
                raise
            finally:
                result['source_identity_after']=product_source_hashes(code)
                (output/'browser.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
                browser.close()
    print(json.dumps({'status':result['status'],'checks':list(result['checks'])},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--code-root',type=Path,default=ROOT)
    parser.add_argument('--baseline',action='store_true')
    args=parser.parse_args()
    run(args.output.resolve(),args.code_root.resolve(),args.baseline)
