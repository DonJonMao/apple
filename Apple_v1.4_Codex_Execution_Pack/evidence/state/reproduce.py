import json, traceback
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zipfile import ZipFile
from xml.sax.saxutils import quoteattr
from healthzip.db.repository import Repository
from healthzip.importers.apple_xml import import_apple_zip
from healthzip.analytics.v13 import analyze
BASE=Path('/workspace/scratch/a74a838d7f65/review912/state')
now=datetime.now(timezone.utc)
def stamp(t):return t.strftime('%Y-%m-%d %H:%M:%S %z')
def record(kind,value,start,end,source='Watch',unit=None,child=''):
 attrs={'type':kind,'value':str(value),'sourceName':source,'sourceVersion':'1','startDate':stamp(start),'endDate':stamp(end)}
 if unit is not None:attrs['unit']=unit
 return '<Record '+ ' '.join(k+'='+quoteattr(v) for k,v in attrs.items())+'>'+child+'</Record>'
def imported(name,records):
 p=BASE/(name+'.sqlite')
 if p.exists():p.unlink()
 r=Repository(p)
 z=BASE/(name+'.zip')
 with ZipFile(z,'w') as f:f.writestr('apple_health_export/export.xml','<HealthData>'+''.join(records)+'</HealthData>')
 imp=import_apple_zip(z,r)
 assert imp.status=='completed',imp.as_dict()
 return r,imp.as_dict()
def small(m):return {k:m[k] for k in ['value','unit','data_status','reason_codes','exclusions']}
results={}
# Valid alternate physical units; no malformed values.
a=(now-timedelta(days=2)).replace(hour=0,minute=0,second=0,microsecond=0);b=a+timedelta(days=1)
r,imp=imported('units',[record('HKQuantityTypeIdentifierBasalEnergyBurned',6694.4,a,b,unit='kJ'),record('HKQuantityTypeIdentifierActiveEnergyBurned',2510.4,a,b,unit='kJ'),record('HKQuantityTypeIdentifierHeartRateVariabilitySDNN',.05,a+timedelta(hours=8),a+timedelta(hours=8,minutes=1),unit='s')])
v=analyze(r,timezone_name='UTC')
results['alternate_units']={'import':imp,'stored':[dict(x) for x in r.rows('SELECT raw_type,raw_value,raw_unit,normalized_value,normalized_unit,unit_status FROM health_sample')],'metrics':{k:small(v['metrics'][k]) for k in ['ENERGY-DEVICE-TOTAL','STATE-SDNN']},'expected':{'device_total_kcal':2200,'SDNN_ms':50}}
r.close()
# Common mixed source: inBed phone records cannot supply asleep duration.
a=now-timedelta(hours=8);b=now-timedelta(hours=1)
r,imp=imported('phone_inbed_watch_asleep',[record('HKCategoryTypeIdentifierSleepAnalysis','HKCategoryValueSleepAnalysisInBed',a-timedelta(hours=1),b,'iPhone'),record('HKCategoryTypeIdentifierSleepAnalysis','HKCategoryValueSleepAnalysisAsleep',a,b,'Watch')])
v=analyze(r,timezone_name='UTC')
results['phone_inbed_watch_asleep']={'import':imp,'metric':small(v['metrics']['STATE-SLEEP-24H']),'report':small(v['metrics']['REPORT-STATE-SUMMARY']),'expected_observed_minutes':420}
r.close()
# Declared historical day boundary; imported facts are known before future synthetic cutoff.
a=(now+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0);cutoff=a+timedelta(days=1)
r,imp=imported('sleep_midnight_boundary',[record('HKCategoryTypeIdentifierSleepAnalysis','HKCategoryValueSleepAnalysisAsleep',a+timedelta(hours=1),a+timedelta(hours=6)),record('HKCategoryTypeIdentifierSleepAnalysis','HKCategoryValueSleepAnalysisAsleep',a+timedelta(hours=23),cutoff)])
try:
 v=analyze(r,window_days=1,cutoff_time=cutoff.isoformat(),timezone_name='UTC')
 results['sleep_midnight_boundary']={'metric':small(v['metrics']['STATE-SLEEP-COVERAGE'])}
except Exception as e:
 results['sleep_midnight_boundary']={'exception_type':type(e).__name__,'message':str(e),'traceback':traceback.format_exc(),'cutoff':cutoff.isoformat(),'window_start':a.isoformat(),'expected':'No exception; numerator must use same half-open local-date domain as denominator'}
r.close()
# Raw nested metadata preservation probe; not promoted to a numeric bug by itself.
r,imp=imported('record_metadata',[record('HKQuantityTypeIdentifierBodyMass',80,now-timedelta(days=1),now-timedelta(days=1),'Scale','kg','<MetadataEntry key="HKWasUserEntered" value="1"/><MetadataEntry key="HKSyncIdentifier" value="scale.measurement.1"/>')])
results['record_metadata']={'stored':[dict(x) for x in r.rows('SELECT metadata_json,source_record_id FROM health_sample')]}
r.close()
(BASE/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
for k,v in results.items(): print(k,json.dumps(v,ensure_ascii=False))
