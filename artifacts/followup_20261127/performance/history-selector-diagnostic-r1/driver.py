import json,os,sys
from pathlib import Path
sys.path.insert(0,'/tmp/healthzip-followup-reports-personal-r6/tests/training')
from strength_workbench_browser_check import isolated_app
from playwright.sync_api import sync_playwright
out=Path('/home/sn_maozhifang/apple/artifacts/followup_20261127/performance/history-selector-diagnostic-r1');out.mkdir()
folder=Path('/tmp/followup-report-browser-hc4wyd0d')
records=[];logs=[]
with isolated_app(folder/'bootstrap',folder) as base, sync_playwright() as p:
 b=p.chromium.launch(headless=True,args=['--no-sandbox']);c=b.new_context(viewport={'width':1440,'height':1000});c.route('http**/*',lambda r:r.continue_() if r.request.url.startswith(base+'/') else r.abort());page=c.new_page()
 page.on('console',lambda m:logs.append({'type':m.type,'text':m.text}));page.on('pageerror',lambda e:logs.append({'error':str(e)}))
 page.goto(base+'/?workspace=review');page.get_by_role('button',name='生成当前周期复盘',exact=True).wait_for(timeout=60000);page.get_by_test_id('stStatusWidget').wait_for(state='hidden');page.get_by_text('已保存的复盘',exact=True).click()
 combo=page.get_by_role('combobox',name='历史复盘',exact=True);combo.evaluate("e=>e.scrollIntoView({block:'center',behavior:'instant'})");page.wait_for_timeout(300)
 for label,act in [('input_click',lambda:combo.click()),('escape',lambda:combo.press('Escape')),('open_button',lambda:combo.locator('xpath=..').get_by_role('button',name='Open',exact=True).click()),('escape2',lambda:combo.press('Escape')),('fill_week',lambda:combo.fill('周复盘')),('arrow_down',lambda:combo.press('ArrowDown')),('alt_down',lambda:combo.press('Alt+ArrowDown'))]:
  try:act()
  except Exception as e:logs.append({'step':label,'error':str(e)})
  page.wait_for_timeout(300)
  record={'label':label,'value':combo.input_value(),'expanded':combo.get_attribute('aria-expanded'),'options':page.get_by_role('option').all_text_contents(),'render':page.locator('[data-hz-render]').get_attribute('data-hz-render')}
  records.append(record);print(record,flush=True);page.screenshot(path=str(out/(label+'.png')));(out/(label+'.html')).write_text(page.content())
 (out/'receipt.json').write_text(json.dumps({'records':records,'console':logs},ensure_ascii=False,indent=2)+'\n');print(logs,flush=True)
 b.close()
