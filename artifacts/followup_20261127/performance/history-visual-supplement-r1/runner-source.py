import hashlib,json,os,shutil,sqlite3,sys,time
from pathlib import Path
from contextlib import closing
repo=Path('/home/sn_maozhifang/apple');source=Path('/tmp/healthzip-followup-final-browser-source-r3-driver4');sys.path.insert(0,str(source/'tools'));sys.path.insert(0,str(source/'tests/training'))
from strength_workbench_browser_check import isolated_app
from followup_report_browser_benchmark import history_input
from followup_report_benchmark import shared_knowledge
from healthzip.ui.review_page import report_history_labels
from playwright.sync_api import sync_playwright
base=repo/'artifacts/followup_20261127/performance';out=base/'history-visual-supplement-r1';out.mkdir(exist_ok=False)
folder=Path(json.loads((base/'final-browser-report-personal-r2/summary.json').read_text())['retained_synthetic_workspace']);database=folder/'.local/healthzip.sqlite3';knowledge=Path('/home/sn_maozhifang/healthzip-followup-validation-tmp/knowledge')
def rows():
 with closing(sqlite3.connect(database)) as c:
  c.row_factory=sqlite3.Row;return [dict(r) for r in c.execute("SELECT report_id,created_at,json_extract(payload_json,'$.period') AS period FROM joint_period_report WHERE user_id='local' ORDER BY created_at DESC LIMIT 30")]
receipt={'source':json.loads((source/'browser-snapshot-origin.json').read_text()),'knowledge_before':shared_knowledge(knowledge),'reports_before':rows(),'scope':'supplemental actual 1440 history pixels; no timing/generation rerun','captures':[]}
def save(): (out/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
shutil.copyfile(__file__,out/'runner-source.py');save()
with isolated_app(folder/'bootstrap',folder) as url,sync_playwright() as p:
 b=p.chromium.launch(headless=True,args=['--no-sandbox']);c=b.new_context(viewport={'width':1440,'height':1000});c.route('http**/*',lambda r:r.continue_() if r.request.url.startswith(url+'/') else r.abort());page=c.new_page()
 try:
  page.goto(url+'/?workspace=review');page.get_by_role('button',name='生成当前周期复盘',exact=True).wait_for(timeout=90000);page.wait_for_function("()=>document.querySelector('[data-hz-render]')?.dataset.workspace==='review'");page.get_by_test_id('stStatusWidget').wait_for(state='hidden');page.get_by_text('已保存的复盘',exact=True).click();selector=page.get_by_role('combobox',name='历史复盘',exact=True);selector.evaluate("e=>e.scrollIntoView({block:'center',behavior:'instant'})");requested=receipt['reports_before'][0]['report_id'];labels=report_history_labels(receipt['reports_before'],'Asia/Shanghai');receipt['selected_report_id']=requested;receipt['selected_label']=labels[requested];receipt['selection_preparation']=history_input(page,selector,labels[requested].rsplit(' ',1)[-1],expected_label=labels[requested]);page.get_by_role('button',name='打开这份复盘',exact=True).click();page.wait_for_function("id=>document.querySelector('[data-hz-report-id]')?.dataset.hzReportId===id",arg=requested,timeout=30000);page.get_by_test_id('stStatusWidget').wait_for(state='hidden');page.get_by_role('heading',name='本期主要变化',exact=True).wait_for()
  if not selector.is_visible():page.get_by_text('已保存的复盘',exact=True).click()
  selector.evaluate("e=>e.scrollIntoView({block:'center',behavior:'instant'})");receipt['menu_preparation']=history_input(page,selector,'周复盘')
  def state():
   return page.evaluate('''()=>{const e=document.querySelector('[role=listbox]');const all=[];for(let p=e;p;p=p.parentElement){const s=getComputedStyle(p);const b=p.getBoundingClientRect();all.push({tag:p.tagName,role:p.getAttribute('role'),class:p.className,opacity:s.opacity,visibility:s.visibility,display:s.display,transform:s.transform,zIndex:s.zIndex,animation:s.animationName,animationState:s.animationPlayState,transition:s.transition,box:{x:b.x,y:b.y,width:b.width,height:b.height}})}const o=document.querySelector('[role=option]');const b=o?.getBoundingClientRect();const hit=b?document.elementFromPoint(b.x+b.width/2,b.y+b.height/2):null;return {expanded:document.querySelector('input[aria-label=历史复盘]')?.getAttribute('aria-expanded'),ancestors:all,options:[...document.querySelectorAll('[role=option]')].map(e=>e.innerText),hit:hit?{tag:hit.tagName,role:hit.getAttribute('role'),text:hit.innerText}:null,animations:document.getAnimations().map(a=>({state:a.playState,currentTime:a.currentTime,target:a.effect?.target?.outerHTML?.slice(0,300)}))}}''')
  receipt['before_paint_wait']=state();save();page.screenshot(path=str(out/'1440-before-paint-wait.png'))
  page.wait_for_function('''()=>{const e=document.querySelector('[role=listbox]');if(!e||!document.querySelector('[role=option]'))return false;for(let p=e;p;p=p.parentElement){const s=getComputedStyle(p);if(Number(s.opacity)<.99||s.visibility==='hidden'||s.display==='none')return false;}return true}''',timeout=5000)
  page.evaluate("()=>Promise.all(document.getAnimations().filter(a=>a.playState==='running'&&a.effect?.getComputedTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>null)))")
  page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');receipt['before_capture']=state();save();page.screenshot(path=str(out/'1440-expanded-painted.png'));receipt['after_capture']=state();receipt['screenshot']='1440-expanded-painted.png';assert receipt['after_capture']['expanded']=='true';assert receipt['after_capture']['options'];receipt['dom_pass']=True;save()
 except Exception as e:
  receipt['failure']=repr(e);page.screenshot(path=str(out/'1440-failure.png'));(out/'1440-failure.html').write_text(page.content());save()
 finally:b.close()
receipt['knowledge_after']=shared_knowledge(knowledge);receipt['reports_after']=rows();receipt['authority_unchanged']=receipt['knowledge_before']==receipt['knowledge_after'];receipt['reports_unchanged']=receipt['reports_before']==receipt['reports_after'];shutil.copyfile(folder/'synthetic-streamlit.log',out/'streamlit.txt');save();print(json.dumps({k:v for k,v in receipt.items() if k in ['dom_pass','failure','authority_unchanged','reports_unchanged','screenshot']},ensure_ascii=False))
