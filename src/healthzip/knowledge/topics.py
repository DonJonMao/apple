"""Public method questions linked to measured fields and review workflows.

The reviewed-use profile is independent of the original frozen metric profiles.
A public question requires no invented health record. Candidate selection,
complete evidence groups, rights and current conflict checks use the same
retriever as personal metric explanations.
"""
from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files

from .store import digest, dumps

# Each topic is a public method question. The keywords describe evidence needs,
# never current values or a user's history.
GROUPS = {
    'comparison': ('K0', '个人变化和误差', 'within-person change variability measurement error important difference missing observations'),
    'heart': ('K1', '心率的采集情境', 'heart rate resting exercise protocol wearable heart rate recovery'),
    'hrv': ('K1', '同条件比较心率变异性', 'heart rate variability SDNN recording posture within-person'),
    'fitness': ('K1', '心肺估计与运动条件', 'oxygen consumption exercise protocol estimated fitness VO2 submaximal workload'),
    'sleep': ('K2', '睡眠时段、分期与覆盖', 'sleep duration timing wake stages sleep diary missing coverage'),
    'night': ('K2', '夜间测量条件', 'sleep wrist temperature oxygen saturation respiratory disturbances measurement'),
    'activity': ('K3', '活动量与活动机会', 'activity participation duration opportunity intensity physical activity'),
    'walking': ('K3', '行走能力与测量任务', 'walking gait mobility speed six minute walk test protocol activity'),
    'strength': ('K4', '同动作负荷和次数比较', 'resistance exercise load repetitions comparable task effort performance'),
    'body': ('K5', '体重与身体组成', 'body mass scale bioelectrical impedance lean body mass conditions'),
    'energy': ('K5', '能量计量与估计', 'energy intake expenditure energy balance device error free living'),
    'environment': ('K6', '环境暴露与覆盖', 'sound exposure equivalent continuous A weighted noise daylight duration'),
    'cycle': ('K7', '周期日志的含义', 'menstrual flow diary self-report symptoms missing training ovulation'),
    'events': ('K2', '设备事件的定义', 'device event notification measurement protocol source official meaning'),
}
FIELDS = {
    'heart': 'heart_rate_bpm workout_heart_rate_bpm resting_heart_rate_bpm walking_heart_rate_bpm heart_rate_recovery_1m',
    'hrv': 'hrv_sdnn_ms', 'fitness': 'vo2_max_ml_kg_min',
    'sleep': 'sleep_stage', 'night': 'sleeping_wrist_temperature_c respiratory_rate_bpm oxygen_saturation_fraction sleep_breathing_disturbances',
    'activity': 'steps distance_walking_running_m distance_cycling_m exercise_minutes stand_hour stand_minutes flights_climbed physical_effort_met',
    'walking': 'six_minute_walk_m walking_speed_m_s walking_step_length_m walking_double_support_fraction walking_asymmetry_fraction walking_steadiness_fraction stair_ascent_m_s stair_descent_m_s',
    'body': 'height_cm body_mass_kg body_fat_fraction lean_body_mass_kg',
    'energy': 'active_energy_kcal basal_energy_kcal dietary_energy_kcal dietary_carbohydrates_g dietary_protein_g dietary_fat_g dietary_water_ml dietary_caffeine_mg',
    'environment': 'daylight_minutes environmental_audio_dba headphone_audio_dba',
    'cycle': 'menstrual_flow intermenstrual_bleeding cervical_mucus_quality ovulation_test_result abdominal_cramps menstrual_cramps',
    'events': 'sleep_apnea_event high_hr_event low_hr_event irregular_rhythm_event walking_steadiness_event environmental_audio_event headphone_audio_event number_of_times_fallen',
}
TOPICS = {'BODY-OBS-' + field: group for group, fields in FIELDS.items() for field in fields.split()}
TOPICS.update(W1='strength', W2='hrv', W3='fitness', W4='comparison', W5='body', W6='sleep',
              W7='walking', W8='cycle', E='events')
PURPOSES = ['measurement', 'comparison', 'mechanism_or_exception', 'action_or_reassessment']
VERSION = 'review-question-use-2026-11-22.1'


def profile(topic):
    group = GROUPS[TOPICS[topic]]
    return {'query': group[1] + ' ' + topic, 'query_aliases': [group[2]],
            'primary_domains': ['wearable', 'strength', 'recovery', 'cardiometabolic', 'physiology'],
            'required_domains': [], 'secondary_domains': [], 'applicability_context': [],
            'required_evidence_types': list(PURPOSES), 'analysis_functions': [],
            'retrieval_profile': 'public_question_method_only'}


def profile_identity(topic):
    return VERSION + ':' + digest(dumps(profile(topic)).encode())[:16]



@lru_cache(maxsize=1)
def _official_definitions():
    return json.loads(files('healthzip.knowledge').joinpath('data/field_originals.json').read_text())


def _definition_links(w, topic):
    field = topic.removeprefix('BODY-OBS-')
    if field == 'workout_heart_rate_bpm':
        field = 'heart_rate_bpm'
    original = _official_definitions().get(field)
    if not original:
        return []
    row = w.lib.sources.execute(
        "SELECT 1 FROM version v JOIN source s USING(source_id) WHERE v.version_id=? AND v.source_id=? "
        "AND v.sha256=? AND s.scientific_state='current' AND NOT EXISTS "
        "(SELECT 1 FROM parse_supersession p WHERE p.old_version_id=v.version_id)",
        (original['version'], original['source_id'], original['sha256'])).fetchone()
    return [dict(original)] if row else []


def question_sources(w, topic, *, mode='lexical', k=6, context=None, release_id=None, services=None):
    from .metric_retrieval import _retrieve_for_metric
    from .revisions import prepare_retrieval_revisions

    if topic not in TOPICS:
        raise ValueError('unknown_public_method_topic')
    prepare_retrieval_revisions(w)
    evidence = _retrieve_for_metric(w, topic, 'explain_metric', None, context, release_id,
                                    mode=mode, k=k, candidate_scope='reviewed_metric', services=services)
    spans = {s['span_id']: s for s in evidence['evidence_spans']}
    items = []
    if not evidence['conflicts']:
        for claim in evidence['matched_claims']:
            citations = []
            for sid in claim['evidence_span_ids']:
                span = spans[sid]
                citations.append({'source_id': span['source_id'], 'version': span['source_version'],
                                  'title': span['source_metadata']['title'], 'url': span['source_metadata']['canonical_url'],
                                  'section': span['section_path'], 'locator': span['locator'], 'span_id': sid})
            items.append({'claim_id': claim['claim_id'], 'version': claim['claim_version'],
                          'statement': ' '.join(claim['statements']), 'limitations': claim['limitations'],
                          'purposes': claim['evidence_types'], 'citations': citations})
    return {'topic': topic, 'catalog': GROUPS[TOPICS[topic]][0], 'items': items,
            'status': 'conflicting' if evidence['conflicts'] else 'available' if items else 'no_applicable_sources',
            'field_definitions': _definition_links(w, topic) if release_id is None else [],
            'retrieval': evidence['retrieval_audit'], 'scientific_authority': 'general_source_context'}
