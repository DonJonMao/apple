import argparse,json,shutil,sqlite3,sys,tempfile
from contextlib import closing
from pathlib import Path
root=Path('/home/sn_maozhifang/apple');sys.path.insert(0,str(root/'tools'))
from followup_report_browser_benchmark import phase
from followup_report_benchmark import shared_knowledge,manifest
output=root/'artifacts/followup_20261127/performance/personal-report-history-shared-smoke-r10';output.mkdir()
old=Path('/tmp/followup-history-smoke-nd12nuvu/.local/healthzip.sqlite3');folder=Path(tempfile.mkdtemp(prefix='followup-history-shared-smoke-'));(folder/'.local').mkdir()
with closing(sqlite3.connect(old.as_uri()+'?mode=ro',uri=True)) as a,closing(sqlite3.connect(folder/'.local/healthzip.sqlite3')) as b:a.backup(b)
shared=Path('/tmp/healthzip-followup-final-knowledge');(folder/'.local/knowledge').symlink_to(shared,target_is_directory=True)
args=argparse.Namespace(source_root=root,output=output,cutoff='2026-11-22T00:00:00+08:00',warm=2)
context={'scope':'reopen driver + shared-knowledge smoke only','existing_report_origin':'personal-report-browser-smoke-r7','workspace':str(folder),'shared_knowledge_authority_before':shared_knowledge(shared,prepare=True),'source':manifest()}
(output/'context.json').write_text(json.dumps(context,indent=2)+'\n')
try:phase(args,folder,folder/'.local/healthzip.sqlite3','reopen')
finally:
 shutil.copyfile(folder/'synthetic-streamlit.log',output/'reopen-streamlit.txt');context['shared_knowledge_authority_after']=shared_knowledge(shared);context['shared_knowledge_unchanged']=context['shared_knowledge_authority_before']==context['shared_knowledge_authority_after'];context['source_unchanged']=context['source']==manifest();(output/'context.json').write_text(json.dumps(context,indent=2)+'\n');assert context['shared_knowledge_unchanged'] and context['source_unchanged']
