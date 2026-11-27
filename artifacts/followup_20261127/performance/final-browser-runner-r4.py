import hashlib,json,os,shutil,subprocess,time
from datetime import datetime,timezone
from pathlib import Path
repo=Path('/home/sn_maozhifang/apple');source=Path('/tmp/healthzip-followup-final-browser-source-r3-driver4');base=repo/'artifacts/followup_20261127/performance';python=repo/'.venv/bin/python';scratch=Path('/home/sn_maozhifang/healthzip-followup-validation-tmp');knowledge=scratch/'knowledge'
context_path=base/'final-browser-run-context-r4.json';assert not context_path.exists()
context={'started_utc':datetime.now(timezone.utc).isoformat(),'source_root':str(source),'snapshot':json.loads((source/'browser-snapshot-origin.json').read_text()),'shared_public_knowledge':str(knowledge),'team_load':'sequential browser acceptance after backend complete; no other team heavy jobs','external_host_load':'uncontrolled, recorded in raw resource samples','os_cache':'retained','remote_model':'not configured; no remote call','physical_device':'shared Kunpeng host Chromium, not real iPhone/Safari','temporary_root':str(scratch),'storage_df_T':subprocess.check_output(['df','-T',str(scratch),'/tmp'],text=True),'public_copy_receipt':'final-browser-public-copy-r1.json','storage_comparison':'browser scratch is on /home, backend scratch was on /tmp; no cross-filesystem speed ratio claimed','retained_generation':'final-browser-report-personal-r2/generation.json (31 successful r3 frozen reports)','retained_personal_pages':['final-browser-detail-personal-r1','final-browser-preview-personal-r1'],'history_preparation':'actual ID input, bounded max3 attempts; preparation timings, scroll/focus events and attempts recorded separately from real Open-click timing','runs':[]}
def save():context_path.write_text(json.dumps(context,ensure_ascii=False,indent=2)+'\n')
shutil.copyfile(__file__,base/'final-browser-runner-r4.py');context['runner_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest();save()
environment={**os.environ,'PLAYWRIGHT_BROWSERS_PATH':'/tmp/healthzip-browser-bin','LD_LIBRARY_PATH':'/tmp/healthzip-browser-libs/extracted/usr/lib/aarch64-linux-gnu','PYTHONPATH':str(source/'src'),'TMPDIR':str(scratch)}
jobs=[('personal','history',None)]
for tier,count in [('100k','100000'),('1m','1000000')]:
 for mode in ['detail','preview','report']:jobs.append((tier,mode,Path('/tmp/healthzip-product-benchmark')/f'synthetic-{count}.sqlite3'))
for tier,mode,database in jobs:
 name=f'final-browser-{mode}-{tier}-'+('r2' if mode in ['detail','preview'] else 'r1');output=base/name;assert not output.exists();resources=base/(name+'-resources.json');log_path=base/(name+'-command.txt')
 if mode=='history':
  task=[str(python),'/tmp/healthzip-final-history-resume-driver4.py','--warm','30','--output',str(output)]
 else:
  task=[str(python),str(source/'tools'/('followup_report_browser_benchmark.py' if mode=='report' else 'followup_page_benchmark.py')),'--database',str(database),'--cutoff','2026-11-22T00:00:00+08:00','--output',str(output),'--warm','30','--concurrent-load',context['team_load']+'; external shared-host load uncontrolled']
  if mode=='report':task+=['--source-root',str(source),'--shared-knowledge-root',str(knowledge)]
  else:task+=['--page',mode]
 command=[str(python),str(source/'tools/repair_measure_run.py'),'--output',str(resources),'--',*task]
 row={'tier':tier,'mode':mode,'command':command,'output':str(output),'log':str(log_path),'started_utc':datetime.now(timezone.utc).isoformat()};context['runs'].append(row);save();started=time.perf_counter();print('START',tier,mode,flush=True)
 with log_path.open('w') as log:result=subprocess.run(command,cwd=repo,env=environment,stdout=log,stderr=subprocess.STDOUT)
 row.update(exit_code=result.returncode,finished_utc=datetime.now(timezone.utc).isoformat(),controller_wall_seconds=time.perf_counter()-started);save()
 if output.exists():
  shutil.copyfile(source/'browser-snapshot-origin.json',output/'snapshot-origin.json')
  for driver in ['followup_report_browser_benchmark.py','followup_page_benchmark.py']:shutil.copyfile(source/'tools'/driver,output/('driver-'+driver))
 print('END',tier,mode,result.returncode,flush=True)
 if result.returncode:context.setdefault('failures',[]).append(row);save()
context['complete']=all(row['exit_code']==0 for row in context['runs']);context['finished_utc']=datetime.now(timezone.utc).isoformat();save()
