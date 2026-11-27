import argparse,json,os,platform,shutil,sqlite3,sys,time
from contextlib import closing
from pathlib import Path
source=Path('/tmp/healthzip-followup-final-browser-source-r3-driver2');repo=Path('/home/sn_maozhifang/apple');sys.path.insert(0,str(source/'tools'))
from followup_report_browser_benchmark import phase
from followup_report_benchmark import manifest,shared_knowledge
parser=argparse.ArgumentParser();parser.add_argument('--warm',type=int,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
prior=json.loads((repo/'artifacts/followup_20261127/performance/final-browser-report-personal-r2/summary.json').read_text());folder=Path(prior['retained_synthetic_workspace']);database=folder/'.local/healthzip.sqlite3';knowledge=Path('/home/sn_maozhifang/healthzip-followup-validation-tmp/knowledge')
args.source_root=source;args.cutoff='2026-11-22T00:00:00+08:00'
def report_ids():
 with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as conn:return [r[0] for r in conn.execute('SELECT report_id FROM joint_period_report ORDER BY created_at DESC')]
context={'scope':'history only; generation31 preserved in final-browser-report-personal-r2/generation.json','generation_origin':'final-browser-report-personal-r2','workspace':str(folder),'source':manifest(),'reports_before':report_ids(),'knowledge_before':shared_knowledge(knowledge),'tmpdir':os.environ.get('TMPDIR'),'platform':platform.platform(),'host_load_before':os.getloadavg(),'os_cache':'retained','remote_model':'not configured','physical_device':'shared host Chromium, no real iPhone/Safari','concurrent_load':'sequential acceptance; other team agents only read documents; outside host load uncontrolled','source_snapshot':json.loads((source/'browser-snapshot-origin.json').read_text())}
path=args.output/'context.json';path.write_text(json.dumps(context,indent=2)+'\n')
try:
 result=phase(args,folder,database,'reopen');context['phase_complete']=result.get('complete');context['reading_captures_pass']=result.get('reading_captures_pass');context['layout_pass']=result.get('layout_pass')
except Exception as exc:context['failure']=repr(exc);raise
finally:
 shutil.copyfile(folder/'synthetic-streamlit.log',args.output/'reopen-streamlit.txt');context['knowledge_after']=shared_knowledge(knowledge);context['authority_unchanged']=context['knowledge_before']==context['knowledge_after'];context['reports_after']=report_ids();context['no_reports_generated']=context['reports_before']==context['reports_after'];context['source_unchanged']=context['source']==manifest();context['host_load_after']=os.getloadavg();path.write_text(json.dumps(context,indent=2)+'\n')
assert context['authority_unchanged'] and context['source_unchanged'] and context['no_reports_generated']
