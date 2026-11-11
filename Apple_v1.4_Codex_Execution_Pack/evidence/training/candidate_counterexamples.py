"""Synthetic real UI/Repository counterexamples; no project file mutations."""
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime, timezone
import importlib.util
import json
import os

from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService

ROOT = Path('/workspace/scratch/a74a838d7f65/apple_review_912aefc')
spec=importlib.util.spec_from_file_location('candidate_test_helpers', ROOT/'tests/integration/test_review_candidate_flow.py')
helpers=importlib.util.module_from_spec(spec); spec.loader.exec_module(helpers)
def now(): return datetime.now(timezone.utc).isoformat()

def cond(svc):
    equipment=svc.create_equipment('Synthetic bench station','barbell')
    return dict(equipment_instance_id=equipment['id'],load_basis='external_total_kg',load_basis_confirmed=True,
        side='both',repetition_semantics='simultaneous',rom_protocol='full',settings_confirmed=True,settings={'grip':'fixed'},
        reference_protocol={'protocol_id':'fixture','version':'1','reference_policy_id':'first-work',
                            'effort_protocol':'rir-2','tempo':'controlled','rest_protocol':'180-sec'})

def complete_ref(svc, instance, *, reps, pain=False, quality='acceptable'):
    row=svc.add_set(instance['id'], {'reference_set': True})
    row=svc.edit_set(row['id'], {'completion_state':'in_progress','started_at':now()}, base_revision=row['revision'])
    return svc.edit_set(row['id'], {'completion_state':'completed','ended_at':now(),'load_value':50,'load_unit':'kg',
        'reps':reps,'rir':2,'quality_status':quality,'pain_flag':pain,'stop_reason':'pain' if pain else 'target_rir'}, base_revision=row['revision'])

def candidate_case(case):
    with TemporaryDirectory(prefix='candidate-review-') as temp:
        os.chdir(temp); path=Path(temp)/'db.sqlite3'
        helpers.synthetic_authority(Path(temp)/'.local/knowledge','external_total_kg')
        repo=Repository(path);svc=TrainingService(repo);condition=cond(svc)
        prior=svc.start_session('prior'); pi=svc.add_exercise(prior['id'],'psa.ex.barbell_bench_press',condition)
        prior_bad=case=='pain_reference'
        record=complete_ref(svc,pi,reps=12,pain=prior_bad,quality='technique_limited' if prior_bad else 'acceptable')
        svc.end_session(prior['id'])
        current=svc.start_session('current'); ci=svc.add_exercise(current['id'],'psa.ex.barbell_bench_press',condition)
        if case=='current_pain':
            complete_ref(svc,ci,reps=4,pain=True,quality='technique_limited')
        target=svc.add_set(ci['id'],planned={'reps_min':6,'reps_max':8,'rir':2})
        repo.close()
        app=helpers.open_app(path)
        app.selectbox(key='candidate_target_'+ci['id']).set_value(target['set_uuid'])
        app.selectbox(key='strategy_'+ci['id']).set_value('heavier_lower_reps' if prior_bad else 'double_progression')
        app.text_input(key='loads_'+ci['id']).set_value('50,52.5,55')
        app.button(key='candidate_'+ci['id']).click().run(timeout=30)
        assert not app.exception and not app.error, ([x.value for x in app.exception],[x.value for x in app.error])
        repo=Repository(path);svc=TrainingService(repo);c=svc.list_recommendations()[0]
        print(json.dumps({'case':case,'prior_quality':record['quality_status'],'prior_pain':bool(record['pain_flag']),
            'action':c['candidate']['action_kind'],'load':c['candidate']['proposed_change']['load'],
            'reasons':c['candidate']['eligibility'],'source_ids':c['input_snapshot']['source_record_ids'],
            'current_set_ids':[s['set_uuid'] for s in svc.get_session(current['id'])['sets']]},ensure_ascii=False))
        repo.close()

candidate_case('pain_reference')
candidate_case('current_pain')

with TemporaryDirectory(prefix='custom-template-review-') as temp:
    os.chdir(temp);repo=Repository(Path(temp)/'db.sqlite3');svc=TrainingService(repo)
    custom=svc.create_exercise('Synthetic custom','repetitions','other','unknown')
    s=svc.start_session('original');i=svc.add_exercise(s['id'],custom['exercise_id'],{})
    svc.add_set(i['id'],planned={'reps_min':6,'reps_max':8,'rir':2})
    updated=svc.update_exercise(custom['exercise_id'],{'recording_mode':'duration'},base_revision=custom['revision'])
    t=svc.save_session_as_template(s['id'],'Saved original task')
    started=svc.start_session(template_id=t['id'])
    print(json.dumps({'case':'custom_version_template','original_definition':i['definition_version'],
        'original_mode':i['condition']['measurement_mode'],'saved_definition':t['items'][0]['definition_version'],
        'saved_mode':t['items'][0]['condition']['measurement_mode'],'saved_targets':t['items'][0]['targets'],
        'started_mode':started['exercises'][0]['condition']['measurement_mode']},ensure_ascii=False))
    repo.close()
