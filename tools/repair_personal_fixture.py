"""Create a separate two-year synthetic personal-use fixture; never alter stress fixtures."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from random import Random
from unittest.mock import patch

from healthzip.db.repository import Repository
from healthzip.training.semantics import timestamp
from healthzip.training.service import TrainingService

CUTOFF = '2026-11-22T00:00:00+08:00'


def create(path):
    if path.exists():
        raise ValueError('new_unused_synthetic_path_required')
    path.parent.mkdir(parents=True,exist_ok=True)
    repo = Repository(path)
    end = datetime.fromisoformat(CUTOFF)
    first = end-timedelta(days=730)
    rng = Random(27112026)
    batch = repo.create_batch(file_sha256='synthetic-personal-two-years-27112026',
        file_name='synthetic-personal-two-years',file_size=0,xml_member_path='')
    counts, months = Counter(), Counter()
    index = 0

    def add(kind,value,at,stop=None,unit='bpm',category=None):
        nonlocal index
        index += 1
        stop = stop or at
        repo.insert_sample(batch,{'fingerprint':f'personal-two-year-{index}',
            'canonical_type':kind,'raw_type':kind,'normalized_value':value,
            'raw_value':str(value) if value is not None else None,'raw_unit':unit,'normalized_unit':unit,
            'start_utc':at.isoformat(),'end_utc':stop.isoformat(),'local_date':stop.date().isoformat(),
            'source_name':'Synthetic personal Watch','source_version':'synthetic-1',
            'device':'synthetic-personal-device','metadata_json':'{"protocol_id":"synthetic-morning"}',
            'category_value':category,'created_at':stop.isoformat()})
        counts[kind] += 1
        months[stop.strftime('%Y-%m')] += 1
    for day in range(730):
        date = first+timedelta(days=day)
        wake = date+timedelta(hours=7)
        add('resting_heart_rate_bpm',round(63+rng.uniform(-3,3),2),wake)
        add('hrv_sdnn_ms',round(42+rng.uniform(-8,8),2),wake+timedelta(minutes=5),unit='ms')
        add('sleep_stage',None,wake-timedelta(minutes=420+rng.randint(-45,45)),wake,
            unit='category',category='HKCategoryValueSleepAnalysisAsleepUnspecified')
        for hour in range(8,21):
            add('heart_rate_bpm',round(75+rng.uniform(-10,20),2),date+timedelta(hours=hour))
    # The synthetic generator, not an import/production migration, declares
    # each original observation available at its event end.
    repo.conn.execute("UPDATE source_revision SET available_at=json_extract(payload_json,'$.end_utc'),"
                      "temporal_provenance='synthetic_acceptance' WHERE table_name='health_sample'")
    repo.conn.commit()
    svc = TrainingService(repo)
    sessions, sets, training_months, training_dates = 0,0,Counter(),[]
    with patch('healthzip.training.service.timestamp',side_effect=lambda value=None: timestamp(value) if value else first.isoformat()):
        equipment = svc.create_equipment('Synthetic stable rack','barbell',equipment_id='synthetic-personal-rack')
    for day in range(730):
        date = first+timedelta(days=day)
        if date.weekday() not in (1,4):
            continue
        at = date+timedelta(hours=18)
        recorded = (at+timedelta(hours=1)).isoformat()
        with patch('healthzip.training.service.timestamp',side_effect=lambda value=None: timestamp(value) if value else recorded):
            session = svc.start_session('Synthetic twice-weekly training',started_at=at.isoformat())
            for exercise in ('psa.ex.barbell_bench_press','psa.ex.barbell_back_squat'):
                condition = {'equipment_instance_id':equipment['id'],'load_basis':'external_total_kg',
                    'load_basis_confirmed':True,'side':'bilateral','repetition_semantics':'total',
                    'rom_protocol':'synthetic-full-range','settings_confirmed':True,'settings':{}}
                if sessions % 11 == 0:
                    condition.pop('rom_protocol')  # Missing stays missing in these new synthetic records.
                instance = svc.add_exercise(session['id'],exercise,condition)
                for position in range(4):
                    svc.add_set(instance['id'],actual={'load_value':30 if 'bench' in exercise else 45,
                        'load_unit':'kg','reps':8+(sessions%3),'rir':None if sessions%5==0 else 0 if position==3 else 2,
                        'set_type':'work','completion_state':'completed',
                        'ended_at':(at+timedelta(minutes=5+position*4)).isoformat()})
                    sets += 1
            svc.end_session(session['id'],ended_at=(at+timedelta(minutes=55)).isoformat())
        sessions += 1
        training_months[date.strftime('%Y-%m')] += 1
        training_dates.append(date.date().isoformat())
    result = {'kind':'separate_personal_synthetic_fixture','cutoff':CUTOFF,'days':730,
        'start':first.isoformat(),'end_exclusive':end.isoformat(),'rng_seed':27112026,
        'health_sample_count':repo.one('SELECT count(*) FROM health_sample')[0],
        'health_types':dict(counts),'health_month_distribution':dict(months),
        'training_session_count':sessions,'training_set_count':sets,
        'training_rule':'Tuesday and Friday, two movements, four completed work sets each; 8 sets/session',
        'training_month_distribution':dict(training_months),'training_dates':training_dates,
        'explicit_unknowns':'Every eleventh session omits ROM; every fifth session omits RIR; other final sets have RIR=0',
        'prespecified_reference':'none','source_record_originals_preserved':True,'database_bytes':path.stat().st_size}
    repo.close()
    path.with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    print(json.dumps(create(args.output),ensure_ascii=False,indent=2))
