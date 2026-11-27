import json,os,sys,sqlite3,shutil,time
from pathlib import Path
repo=Path('/home/sn_maozhifang/apple'); source=Path('/tmp/healthzip-followup-final-browser-source-r3-driver2');sys.path.insert(0,str(source/'tests/training'))
from strength_workbench_browser_check import isolated_app
from playwright.sync_api import sync_playwright
out=repo/'artifacts/followup_20261127/performance/history-selector-diagnostic-r3';out.mkdir()
prior=json.loads((repo/'artifacts/followup_20261127/performance/final-browser-report-personal-r2/summary.json').read_text());folder=Path(prior['retained_synthetic_workspace']);db=folder/'.local/healthzip.sqlite3'
with sqlite3.connect(db) as c: ids=[r[0] for r in c.execute("SELECT report_id FROM joint_period_report WHERE user_id='local' ORDER BY created_at DESC LIMIT 30")]
records=[];logs=[];websockets=[]
with isolated_app(folder/'bootstrap',folder) as base,sync_playwright() as p:
 b=p.chromium.launch(headless=True,args=['--no-sandbox']);c=b.new_context(viewport={'width':1440,'height':1000});c.route('http**/*',lambda r:r.continue_() if r.request.url.startswith(base+'/') else r.abort());page=c.new_page()
 page.on('console',lambda m:logs.append({'type':m.type,'text':m.text}));page.on('pageerror',lambda e:logs.append({'error':str(e)}))
 def socket(ws):
  ws.on('framesent',lambda payload:websockets.append({'direction':'sent','at':time.time(),'bytes':len(payload)}));ws.on('framereceived',lambda payload:websockets.append({'direction':'received','at':time.time(),'bytes':len(payload)}))
 page.on('websocket',socket)
 page.goto(base+'/?workspace=review');page.get_by_role('button',name='生成当前周期复盘',exact=True).wait_for(timeout=90000);page.wait_for_function("()=>document.querySelector('[data-hz-render]')?.dataset.workspace==='review'");page.get_by_test_id('stStatusWidget').wait_for(state='hidden')
 page.evaluate('''()=>{window.__events=[];let last='';function snap(kind){let e=document.querySelector('input[role=combobox][aria-label=历史复盘]');let v={at:performance.now(),kind,value:e?.value,expanded:e?.getAttribute('aria-expanded'),focus:document.activeElement?.outerHTML.slice(0,350),render:document.querySelector('[data-hz-render]')?.dataset.hzRender,options:document.querySelectorAll('[role=option]').length,status:!!document.querySelector('[data-testid=stStatusWidget]')};let key=JSON.stringify({...v,at:0,kind:''});if(kind!=='mutation'||key!==last){window.__events.push(v);last=key;}}['click','focusin','focusout','keydown','input'].forEach(k=>document.addEventListener(k,()=>snap(k),true));new MutationObserver(()=>snap('mutation')).observe(document.body,{subtree:true,attributes:true,childList:true});snap('start');}''')
 page.get_by_text('已保存的复盘',exact=True).click();combo=page.get_by_role('combobox',name='历史复盘',exact=True);combo.evaluate("e=>e.scrollIntoView({block:'center',behavior:'instant'})");page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
 def save(label):
  record={'label':label,'value':combo.input_value(),'expanded':combo.get_attribute('aria-expanded'),'options':page.get_by_role('option').all_text_contents(),'render':page.locator('[data-hz-render]').get_attribute('data-hz-render'),'events':page.evaluate('window.__events')};records.append(record);print(json.dumps({k:v for k,v in record.items() if k!='events'},ensure_ascii=False),flush=True);page.screenshot(path=str(out/(label+'.png')));(out/(label+'.html')).write_text(page.content());(out/'receipt.json').write_text(json.dumps({'records':records,'console':logs,'websockets':websockets,'ids':ids},ensure_ascii=False,indent=2)+'\n')
 def attempt(label,func):
  try:
   func();page.wait_for_function("()=>document.querySelector('input[role=combobox][aria-label=历史复盘]')?.getAttribute('aria-expanded')==='true'",timeout=2500)
  except Exception as e:logs.append({'step':label,'error':str(e)})
  save(label)
 save('before')
 attempt('direct_arrow',lambda:combo.locator('xpath=..').get_by_role('button',name='Open',exact=True).click())
 combo.press('Escape');combo.click();attempt('focus_then_arrow',lambda:combo.locator('xpath=..').get_by_role('button',name='Open',exact=True).click())
 combo.press('Escape');combo.click();combo.press('Control+a');attempt('unique_id_typing',lambda:combo.press_sequentially(ids[1][:8]))
 if page.get_by_role('option').count()==1:
  chosen=page.get_by_role('option').inner_text();page.get_by_role('option').click();page.get_by_test_id('stStatusWidget').wait_for(state='hidden');save('unique_id_selected');print({'chosen':chosen,'requested':ids[1]},flush=True)
 b.close()
shutil.copyfile(folder/'synthetic-streamlit.log',out/'streamlit.txt');shutil.copyfile(__file__,out/'runner-source.py')
