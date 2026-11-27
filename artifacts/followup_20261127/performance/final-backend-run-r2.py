from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,os,subprocess,time
repo=Path('/home/sn_maozhifang/apple')
source=Path('/tmp/healthzip-followup-final-source-r2')
kb=Path('/tmp/healthzip-followup-final-knowledge')
base=repo/'artifacts/followup_20261127/performance'
identity=json.loads((source/'archive-identity.json').read_text())
changed=[name for name,digest in identity['files'].items() if hashlib.sha256((source/name).read_bytes()).hexdigest()!=digest]
assert not changed,changed
assert identity==json.loads((repo/'artifacts/followup_20261127/validation/completion-source-r2.json').read_text())
clock=lambda:datetime.now(timezone.utc).isoformat()
context={'started_utc':clock(),'source_root':str(source),'source_archive_manifest_sha256':hashlib.sha256((source/'archive-identity.json').read_bytes()).hexdigest(),'source_base_commit':identity['base_commit'],'source_manifest_files':len(identity['files']),'source_preflight_exact':True,'shared_public_knowledge_root':str(kb),'os_cache':'retained','remote_model':'not configured in isolated acceptance','physical_device':'shared Kunpeng-920/aarch64 host; not ordinary-device proof','team_load':'sequential backend only; no other agent heavy jobs','external_shared_host_load':'uncontrolled; recorded by each phase','tiers':[]}
context_path=base/'final-backend-run-context-r2.json'
assert not context_path.exists()
context_path.write_text(json.dumps(context,ensure_ascii=False,indent=2)+'\n')
fixtures=[('personal',Path('/tmp/healthzip-repair-personal/synthetic-two-year.sqlite3')),('100k',Path('/tmp/healthzip-product-benchmark/synthetic-100000.sqlite3')),('1m',Path('/tmp/healthzip-product-benchmark/synthetic-1000000.sqlite3'))]
for tier,fixture in fixtures:
    output=base/f'final-backend-{tier}-r2'
    logpath=base/f'final-backend-{tier}-r2-command.txt'
    assert not output.exists() and not logpath.exists()
    command=[str(repo/'.venv/bin/python'),str(source/'tools/followup_report_benchmark.py'),'--synthetic',str(fixture),'--shared-knowledge-root',str(kb),'--output',str(output),'--warm','30','--concurrent-load','Sequential final acceptance; no other agent heavy jobs; external shared-host load uncontrolled']
    entry={'tier':tier,'started_utc':clock(),'command':command,'environment':{'PYTHONPATH':str(source/'src')},'output':str(output),'log':str(logpath)}
    context['tiers'].append(entry)
    context_path.write_text(json.dumps(context,ensure_ascii=False,indent=2)+'\n')
    print('START',tier,entry['started_utc'],flush=True)
    started=time.perf_counter()
    with logpath.open('x') as logfile:
        completed=subprocess.run(command,cwd=repo,env={**os.environ,'PYTHONPATH':str(source/'src')},stdout=logfile,stderr=subprocess.STDOUT)
    entry.update(finished_utc=clock(),exit_code=completed.returncode,controller_wall_seconds=time.perf_counter()-started)
    context_path.write_text(json.dumps(context,ensure_ascii=False,indent=2)+'\n')
    print('FINISH',tier,entry['exit_code'],entry['controller_wall_seconds'],flush=True)
    if completed.returncode:
        raise SystemExit(completed.returncode)
context.update(finished_utc=clock(),complete=True)
context_path.write_text(json.dumps(context,ensure_ascii=False,indent=2)+'\n')
