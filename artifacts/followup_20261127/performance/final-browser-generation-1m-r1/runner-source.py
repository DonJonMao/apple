import argparse,hashlib,json,os,platform,shutil,sqlite3,sys,tempfile
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
source=Path('/tmp/healthzip-followup-final-browser-source-r3-driver4');sys.path.insert(0,str(source/'tools'))
from followup_report_browser_benchmark import phase
from followup_report_benchmark import manifest,shared_knowledge,validate_synthetic
from repair_preview_benchmark import fixture_copy
parser=argparse.ArgumentParser();parser.add_argument('--database',type=Path);parser.add_argument('--reuse-generation',type=Path);parser.add_argument('--phase',choices=['generation','reopen'],required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--warm',type=int,default=30);args=parser.parse_args();args.source_root=source;args.cutoff='2026-11-22T00:00:00+08:00';args.output.mkdir(parents=True,exist_ok=False)
knowledge=Path('/home/sn_maozhifang/healthzip-followup-validation-tmp/knowledge');before_source=manifest();measured={str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [*source.joinpath('src').rglob('*.py'),source/'app.py',source/'.streamlit/config.toml']}
result={'started_utc':datetime.now(timezone.utc).isoformat(),'phase':args.phase,'synthetic_only':True,'source_root':str(source),'source_snapshot':json.loads((source/'browser-snapshot-origin.json').read_text()),'platform':platform.platform(),'logical_cpu':os.cpu_count(),'initial_host_load':os.getloadavg(),'concurrent_load':'independent sequential browser phase; no team heavy jobs; outside host load uncontrolled','os_cache_cleared':False,'remote_model':'not configured/no remote calls','physical_safari':'not tested','clock':'actual DOM generate/open click to new report ID/real finding/new plotted frozen values/UI interactive','phases':[],'shared_knowledge_authority_before':shared_knowledge(knowledge,prepare=True)}
if args.phase=='generation':
 assert args.database is not None and args.reuse_generation is None;validate_synthetic(args.database);folder=Path(tempfile.mkdtemp(prefix='followup-report-phase-'));database,counts=fixture_copy(args.database,folder);(folder/'.local/knowledge').symlink_to(knowledge,target_is_directory=True);result['counts']=counts;result['original_synthetic_fixture']=str(args.database)
else:
 assert args.reuse_generation is not None and args.database is None;prior=json.loads(args.reuse_generation.read_text());assert prior.get('complete');folder=Path(prior['retained_synthetic_workspace']);database=folder/'.local/healthzip.sqlite3';result['generation_origin']=str(args.reuse_generation)
result['retained_synthetic_workspace']=str(folder)
def ids():
 with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as c:
  exists=c.execute("SELECT 1 FROM sqlite_master WHERE name='joint_period_report'").fetchone();return [r[0] for r in c.execute('SELECT report_id FROM joint_period_report ORDER BY created_at DESC')] if exists else []
result['reports_before']=ids()
def save(): (args.output/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
(args.output/'source-manifest.json').write_text(json.dumps(before_source,indent=2)+'\n');(args.output/'measured-source-manifest.json').write_text(json.dumps(measured,indent=2)+'\n');shutil.copyfile(__file__,args.output/'runner-source.py');shutil.copyfile(source/'tools/followup_report_browser_benchmark.py',args.output/'driver-source.py');shutil.copyfile(source/'browser-snapshot-origin.json',args.output/'snapshot-origin.json');save()
try:
 result['phases'].append(phase(args,folder,database,args.phase));result['complete']=True
except Exception as exc:result['failure']=repr(exc);raise
finally:
 log=folder/'synthetic-streamlit.log'
 if log.exists():shutil.copyfile(log,args.output/(args.phase+'-streamlit.txt'))
 result['source_changed']=before_source!=manifest();result['measured_source_changed']=any(hashlib.sha256((source/name).read_bytes()).hexdigest()!=digest for name,digest in measured.items());result['shared_knowledge_authority_after']=shared_knowledge(knowledge);result['shared_knowledge_authority_unchanged']=result['shared_knowledge_authority_before']==result['shared_knowledge_authority_after'];result['reports_after']=ids();result['no_reports_generated']=result['reports_before']==result['reports_after'] if args.phase=='reopen' else None;result['finished_utc']=datetime.now(timezone.utc).isoformat();result['final_host_load']=os.getloadavg();save()
assert not result['source_changed'] and not result['measured_source_changed'] and result['shared_knowledge_authority_unchanged']
if args.phase=='reopen':assert result['no_reports_generated']
