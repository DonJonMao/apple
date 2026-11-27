import argparse,json,shutil,sqlite3,sys,tempfile
from contextlib import closing
from pathlib import Path
root=Path('/tmp/healthzip-followup-reports-personal-r9');sys.path.insert(0,str(root/'tools'))
from followup_report_browser_benchmark import phase
output=Path('/home/sn_maozhifang/apple/artifacts/followup_20261127/performance/personal-report-history-smoke-r9');output.mkdir()
previous=json.loads(Path('/home/sn_maozhifang/apple/artifacts/followup_20261127/performance/personal-report-browser-smoke-r7/summary.json').read_text())
old=Path(previous['retained_synthetic_workspace']);folder=Path(tempfile.mkdtemp(prefix='followup-history-smoke-'));(folder/'.local/knowledge').mkdir(parents=True)
for name in ['healthzip.sqlite3','knowledge/sources.sqlite3','knowledge/theories.sqlite3']:
 with closing(sqlite3.connect((old/'.local'/name).as_uri()+'?mode=ro',uri=True)) as a, closing(sqlite3.connect(folder/'.local'/name)) as b:a.backup(b)
args=argparse.Namespace(source_root=root,output=output,cutoff='2026-11-22T00:00:00+08:00',warm=2)
(output/'context.json').write_text(json.dumps({'scope':'reopen-driver-smoke-only','existing_report_origin':'personal-report-browser-smoke-r7','retained_synthetic_workspace':str(folder)},indent=2)+'\n');shutil.copyfile(root/'snapshot.json',output/'snapshot-origin.json')
try:phase(args,folder,folder/'.local/healthzip.sqlite3','reopen')
finally:shutil.copyfile(folder/'synthetic-streamlit.log',output/'reopen-streamlit.txt')
