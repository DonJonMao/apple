import gzip,hashlib,json,os,time
from pathlib import Path
exclude='/tmp/followup-history-smoke-nd12nuvu/.local/knowledge'
folders=[Path(s) for s in json.loads(Path('/tmp/healthzip-calendar-agent-public-backup-paths.json').read_text()) if s!=exclude]
output=Path('/home/sn_maozhifang/apple/artifacts/followup_20261127/performance/public-backup-archive-receipt.json')
receipt={'purpose':'lossless archive of exited diagnostic public literature copies only','excluded_running':exclude,'files':[]}

def opened(paths):
 found=[];own_unreadable=[]
 wanted={str(p.resolve()) for p in paths}
 for proc in Path('/proc').iterdir():
  if not proc.name.isdigit():continue
  try:
   for fd in (proc/'fd').iterdir():
    try:target=os.readlink(fd)
    except (FileNotFoundError,PermissionError):continue
    if target in wanted:found.append({'pid':int(proc.name),'fd':str(fd),'path':target})
  except FileNotFoundError:continue
  except PermissionError:
   try:
    if proc.stat().st_uid==os.getuid():own_unreadable.append(proc.name)
   except FileNotFoundError:pass
 
 for pid in own_unreadable:
  proc=Path('/proc')/pid
  name=(proc/'comm').read_text().strip()
  assert name in {'sshd','(sd-pam)'}, (pid,name)
 receipt['unreadable_non_application_processes']=[{'pid':pid,'comm':(Path('/proc')/pid/'comm').read_text().strip()} for pid in own_unreadable]
 return found

for folder in folders:
 paths=[p for name in ['sources.sqlite3','theories.sqlite3'] for p in [folder/name,folder/(name+'-wal'),folder/(name+'-shm')] if p.exists()]
 assert not opened(paths),opened(paths)
 for source in paths:
  assert not opened([source]),opened([source])
  before=source.stat();dest=source.with_name(source.name+'.gz');partial=source.with_name(source.name+'.gz.partial');assert not dest.exists() and not partial.exists()
  digest=hashlib.sha256()
  with source.open('rb') as src,partial.open('xb') as raw,gzip.GzipFile(filename='',mode='wb',compresslevel=1,fileobj=raw,mtime=0) as compressed:
   while chunk:=src.read(4*1024*1024):digest.update(chunk);compressed.write(chunk)
  with gzip.open(partial,'rb') as restored:actual=hashlib.file_digest(restored,'sha256').hexdigest()
  assert actual==digest.hexdigest()
  after=source.stat();assert (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns)
  assert not opened([source]),opened([source])
  partial.rename(dest)
  record={'original':str(source),'archive':str(dest),'original_bytes':before.st_size,'archive_bytes':dest.stat().st_size,'sha256':actual,'gzip_roundtrip_exact':True,'open_file_handles_before_removal':[],'removed_uncompressed':False}
  receipt['files'].append(record);output.write_text(json.dumps(receipt,indent=2)+'\n')
  source.unlink();record['removed_uncompressed']=True;output.write_text(json.dumps(receipt,indent=2)+'\n');print(record,flush=True)
 (folder/'RESTORE.txt').write_text('Public literature diagnostic copies archived losslessly. Health databases/reports/evidence are unchanged.\nRestore each *.sqlite3.gz (and any *-wal.gz/*-shm.gz) to a NEW directory with gzip -dc before opening SQLite. Do not overwrite an existing database.\nEach SHA256 and exact roundtrip proof: '+str(output)+'\n')
receipt['complete']=True;receipt['saved_bytes']=sum(r['original_bytes']-r['archive_bytes'] for r in receipt['files']);output.write_text(json.dumps(receipt,indent=2)+'\n')
print('SAVED',receipt['saved_bytes'],flush=True)
