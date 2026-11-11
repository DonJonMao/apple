import json, resource, tempfile, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from healthzip.db.repository import Repository
from healthzip.importers.apple_xml import import_apple_zip
from healthzip.analytics.v13 import analyze

results=[]
for n in (0, 10000, 50000):
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        repo=Repository(root/'synthetic.sqlite3')
        if n:
            base=datetime(2020,1,1,tzinfo=timezone.utc)
            with ZipFile(root/'synthetic.zip','w',compression=ZIP_DEFLATED) as z:
                with z.open('export.xml','w') as f:
                    f.write(b'<HealthData>')
                    for i in range(n):
                        t=(base+timedelta(minutes=i)).strftime('%Y-%m-%d %H:%M:%S +0000')
                        f.write((f'<Record type="HKQuantityTypeIdentifierHeartRate" unit="count/min" value="70" sourceName="SyntheticBench" startDate="{t}" endDate="{t}"/>').encode())
                    f.write(b'</HealthData>')
            imported=import_apple_zip(root/'synthetic.zip',repo)
        started=time.perf_counter()
        out=analyze(repo,window_days=30)
        elapsed=time.perf_counter()-started
        result={'all_rows':n,'window_days':30,'all_sample_dates':'2020, outside 2026 window','analysis_seconds':round(elapsed,3),'maxrss_kib_process_highwater':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'available_in_sleep':out['metrics']['STATE-SLEEP-24H']['input_available_n']}
        results.append(result)
        print(json.dumps(result),flush=True)
        repo.close()
Path('/workspace/scratch/a74a838d7f65/review912/history_benchmark.json').write_text(json.dumps(results,indent=2))
