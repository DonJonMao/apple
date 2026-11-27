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

# Substantive public answer targets, separate from the immutable metric-use
# profile. A purpose tag alone does not establish that this question is answered.
ANSWER_NEEDS_VERSION = 'public-topic-answer-needs-2'
ANSWER_NEEDS = {
    'hrv_metric_and_recording_identity': {
        'topics': ['BODY-OBS-hrv_sdnn_ms'],
        'purposes': ['measurement', 'comparison'],
        'question': 'SDNN与RMSSD是否是同一指标，记录片段长度改变时能否直接比较？',
        'query': 'SDNN RMSSD definition recording epoch length comparability',
        'target_claim': {'proposition': 'SDNN与RMSSD定义不同，比较HRV必须保留记录长度和片段构成。',
                         'scope': {'use': 'hrv_definition_and_recording_identity',
                                   'device_accuracy': 'not_established'}},
    },
    'training_state_measurement_context': {
        'topics': ['W2'],
        'purposes': ['measurement', 'action_or_reassessment'],
        'question': '核对训练后心率和HRV时，测量情境未知应先补记什么？',
        'query': 'heart rate HRV activity posture sleep wake context recording reassessment',
        'target_claim': {'proposition': '先分开同姿势和低活动等可比片段，情境未知时补记测量时正在做什么。',
                         'scope': {'use': 'record_actual_measurement_context',
                                   'unrecorded_fatigue_or_illness': 'not_inferred'}},
    },
    'hrv_direction_and_training_response': {
        'topics': ['BODY-OBS-hrv_sdnn_ms', 'W2', 'W6'],
        'purposes': ['mechanism_or_exception', 'action_or_reassessment'],
        'question': 'HRV的升降能否单独判定训练反应，复评还需要核对什么？',
        'query': 'heart rate variability direction overreaching performance fatigue training response interpretation',
        'target_claim': {'proposition': 'HRV变化方向不足以单独判定训练反应，需要结合实际表现与测量条件。',
                         'scope': {'use': 'training_response_interpretation_limits',
                                   'metric': 'HRV_not_interchangeable_SDNN_RMSSD',
                                   'individual_threshold': 'not_established'}},
    },
    'wearable_hrv_protocol_transfer': {
        'topics': ['BODY-OBS-hrv_sdnn_ms'],
        'purposes': ['measurement', 'comparison'],
        'question': '某设备夜间RMSSD或心率的一致性，能否证明短时段或自由活动SDNN同样准确？',
        'query': 'PPG ECG wearable nocturnal RMSSD SDNN short term free living accuracy comparability',
        'target_claim': {'proposition': '特定PPG设备夜间RMSSD或心率的一致性不能直接验证短时段或自由活动SDNN。',
                         'scope': {'use': 'measurement_validation_transfer_limits',
                                   'metric': 'SDNN_separate_from_RMSSD_and_heart_rate',
                                   'current_device_accuracy': 'not_established'}},
    },
    'hrv_missing_observation_unit': {
        'topics': ['BODY-OBS-hrv_sdnn_ms', 'W2', 'W6'],
        'purposes': ['measurement', 'comparison'],
        'question': '心搏片段内缺少数据，与整日没有HRV记录，能否用同一缺失规则处理？',
        'query': 'missing interbeat intervals five minute window absent days HRV observation unit',
        'target_claim': {'proposition': '心搏片段内的缺口研究不能建立整日HRV缺测的容忍天数。',
                         'scope': {'use': 'within_window_missingness_not_absent_days',
                                   'minimum_observation_days': 'not_established'}},
    },
    'repetition_load_population_transfer': {
        'topics': ['W1'],
        'purposes': ['comparison', 'mechanism_or_exception'],
        'question': '群体次数与最大负荷百分比的关系，能否确定本人或另一动作的负荷换算？',
        'query': 'repetitions percentage one repetition maximum individual variation bench press leg press',
        'target_claim': {'proposition': '次数与最大负荷百分比的群体模型不提供个人或跨动作的确定性换算。',
                         'scope': {'use': 'population_repetition_load_model_limits',
                                   'individual_conversion': 'not_established'}},
    },
    'measured_estimated_1rm_reliability': {
        'topics': ['W1'],
        'purposes': ['measurement', 'comparison'],
        'question': '直接测试1RM的重测可靠性，是否也验证了由普通训练推算的e1RM？',
        'query': 'direct one repetition maximum test retest reliability estimated 1RM measurement error',
        'target_claim': {'proposition': '直接1RM测试的重测可靠性不能直接转移给训练记录推算的e1RM。',
                         'scope': {'use': 'direct_1rm_reliability_not_e1rm_validation',
                                   'individual_estimate_error': 'not_established'}},
    },
    'watch_oxygen_agreement_scope': {
        'topics': ['BODY-OBS-oxygen_saturation_fraction'],
        'purposes': ['measurement', 'comparison', 'mechanism_or_exception'],
        'question': 'Apple Watch血氧研究的平均偏差小，是否代表本人每次读数准确？',
        'query': 'Apple Watch Series 6 8 blood oxygen mean bias limits agreement hypoxic measurement conditions',
        'target_claim': {'proposition': '所研究Apple Watch血氧的平均偏差与单次读数一致性不同，不能由均值认定个人读数准确。',
                         'scope': {'use': 'reviewed_spo2_agreement_scope',
                                   'device_scope': 'studied_Series_6_to_8',
                                   'personal_error_bound': 'not_established'}},
    },
    'watch_steps_validation_scope': {
        'topics': ['BODY-OBS-steps'],
        'purposes': ['measurement', 'comparison'],
        'question': '早期Apple Watch步数验证，是否已覆盖当前型号和坐着活动手臂等场景？',
        'query': 'Apple Watch First Generation Series 1 step count validation seated arm movement',
        'target_claim': {'proposition': '所汇总早期Apple Watch步数研究未验证全部后续型号或坐着活动手臂等场景。',
                         'scope': {'use': 'step_count_validation_transfer_limits',
                                   'device_scope': 'First_Generation_and_Series_1'}},
    },
    'watch_night_vital_validation_scope': {
        'topics': ['BODY-OBS-respiratory_rate_bpm', 'BODY-OBS-sleeping_wrist_temperature_c'],
        'purposes': ['measurement', 'comparison'],
        'question': '已有Apple Watch其他指标的验证，是否已证明呼吸率和腕温的变化准确？',
        'query': 'Apple Watch respiratory rate wrist temperature longitudinal validation evidence gaps',
        'target_claim': {'proposition': '该Apple Watch综述仍要求验证呼吸率和腕温，其他指标的结果不提供其个人变化精度。',
                         'scope': {'use': 'review_specific_respiratory_and_wrist_temperature_gap',
                                   'all_literature_absent': False,
                                   'individual_change_threshold': 'not_established'}},
    },
}


def answer_targets(bindings, context=None):
    from .applicability import context_match
    from .support import target_key
    return {target_key(binding['target_claim']) for binding in bindings
            if binding.get('answer_complete') is True and binding.get('target_coverage_complete') is True
            and context_match(binding.get('required_context', {}), context or {})[0]}


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


def question_sources(w, topic, *, mode='lexical', k=6, context=None, release_id=None, services=None,
                     required_purposes=None, include_evidence=False):
    from .metric_retrieval import _retrieve_for_metric, claim_conflicts
    from .revisions import prepare_retrieval_revisions

    if topic not in TOPICS:
        raise ValueError('unknown_public_method_topic')
    needs = list(PURPOSES if required_purposes is None else required_purposes)
    if not set(needs) <= set(PURPOSES):
        raise ValueError('unknown_public_question_purpose')
    from .support import target_key
    requested_answers = {key: target_key(spec['target_claim']) for key, spec in ANSWER_NEEDS.items()
                         if topic in spec['topics'] and set(needs) & set(spec['purposes'])}
    prepare_retrieval_revisions(w)
    evidence = _retrieve_for_metric(w, topic, 'explain_metric', None, context, release_id,
                                    mode=mode, k=k, candidate_scope='reviewed_metric', services=services,
                                    answer_priorities=list(requested_answers) or None)
    covered = {p for c in evidence['matched_claims'] if not claim_conflicts(c, evidence['conflicts'])
               for p in c['evidence_types']}
    missing = sorted(set(needs) - covered)
    initial_audit = evidence['retrieval_audit']
    available = {p for g in initial_audit.get('metric_candidate_scope', {}).get('complete_group_refs', [])
                 for p in g.get('evidence_types', [])}
    answered = {target for claim in evidence['matched_claims'] if not claim_conflicts(claim, evidence['conflicts'])
                for target in answer_targets(claim.get('answer_bindings', []), context)}
    available_answers = {target for group in initial_audit.get('metric_candidate_scope', {}).get('complete_group_refs', [])
                         for target in answer_targets(group.get('answer_bindings', []), context)}
    missing_answers = [key for key, target in requested_answers.items() if target not in answered]
    supplemental_answers = [key for key in missing_answers if requested_answers[key] in available_answers]
    supplemental_needs = sorted(set(missing) & available)
    supplemental_audit = None
    if supplemental_needs or supplemental_answers:
        # One bounded local pass for missing uses; never raise the global top-k,
        # split complete groups or spend additional remote model calls.
        supplement = _retrieve_for_metric(w, topic, 'explain_metric', None, context, release_id,
            mode='lexical', k=min(k, 6), candidate_scope='reviewed_metric', purpose_needs=supplemental_needs or None,
            answer_needs=supplemental_answers or None)
        supplemental_audit = supplement['retrieval_audit']
        spans = {s['span_id']: s for s in evidence['evidence_spans']}
        claims = {(c['claim_id'], c['claim_version'], c['metric_relation']): c
                  for c in evidence['matched_claims']}
        for claim in supplement['matched_claims']:
            if (set(claim['evidence_types']) & set(missing) or answer_targets(claim.get('answer_bindings', []), context)
                    & {requested_answers[key] for key in supplemental_answers}):
                claims[(claim['claim_id'], claim['claim_version'], claim['metric_relation'])] = claim
                spans.update({s['span_id']: s for s in supplement['evidence_spans']
                              if s['span_id'] in claim['evidence_span_ids']})
        evidence['matched_claims'] = list(claims.values())
        evidence['evidence_spans'] = list(spans.values())
        evidence['conflicts'] = list({dumps(c): c for c in
            [*evidence['conflicts'], *supplement['conflicts']]}.values())
    spans = {s['span_id']: s for s in evidence['evidence_spans']}
    items, restricted, reviews = [], [], {}
    for claim in evidence['matched_claims']:
        from .core import _claim
        try:
            for ref in [{'claim_id': claim['claim_id'], 'claim_version': claim['claim_version']},
                        *claim.get('required_claim_refs', [])]:
                _, review, _ = _claim(w, {'claim_id': ref['claim_id'], 'version': ref['claim_version']})
                reviews[(ref['claim_id'], ref['claim_version'])] = {
                    'claim_id': ref['claim_id'], 'claim_version': ref['claim_version'], 'review': review}
        except ValueError:
            continue  # Current revocation wins over an earlier pass in this request.
        citations = []
        for sid in claim['evidence_span_ids']:
            span = spans[sid]
            citations.append({'source_id': span['source_id'], 'version': span['source_version'],
                              'title': span['source_metadata']['title'], 'url': span['source_metadata']['canonical_url'],
                              'section': span['section_path'], 'locator': span['locator'], 'span_id': sid})
        conflicts = claim_conflicts(claim, evidence['conflicts'])
        item = {'claim_id': claim['claim_id'], 'version': claim['claim_version'],
                'statement': ' '.join(claim['statements']), 'limitations': claim['limitations'],
                'scope': claim['scope'], 'reviewer_kind': claim.get('reviewer_kind'),
                'required_claim_refs': claim.get('required_claim_refs', []),
                'answer_bindings': claim.get('answer_bindings', []),
                'purposes': claim['evidence_types'], 'citations': citations}
        if conflicts:
            item.update(reason='conflicting_claim_or_required_premise', conflicts=conflicts,
                        recommendation_allowed=False)
            restricted.append(item)
        else:
            items.append(item)
    covered = {p for c in items for p in c['purposes']}
    answered = {target for item in items for target in answer_targets(item.get('answer_bindings', []), context)}
    disputed_answers = {target for item in restricted for target in answer_targets(item.get('answer_bindings', []), context)}
    audit = {**initial_audit, 'question_selection_version': 'bounded-topic-use-3',
             'required_purposes': needs, 'initial_missing_purposes': missing,
             'answer_needs_version': ANSWER_NEEDS_VERSION, 'initial_missing_answers': missing_answers,
             'answer_status': {key: {'question': ANSWER_NEEDS[key]['question'],
                 'status': ('available' if target in answered else 'locally_conflicted' if target in disputed_answers
                            else 'complete_group_budget_or_rank' if target in available_answers else 'no_current_applicable_reviewed_answer')}
                 for key, target in requested_answers.items()},
             'supplemental_pass': supplemental_audit, 'supplemental_remote_calls': 0,
             'maximum_unique_spans': k + min(k, 6), 'selected_unique_spans': len(spans),
             'purpose_status': {p: ('available' if p in covered else
                 'locally_conflicted' if any(p in c['purposes'] for c in restricted) else
                 'complete_group_budget_or_rank' if p in available else
                 'no_current_applicable_reviewed_group') for p in needs}}
    result = {'topic': topic, 'catalog': GROUPS[TOPICS[topic]][0], 'items': items,
            'restricted_items': restricted, 'conflicts': evidence['conflicts'],
            'status': ('partial_conflict' if items else 'conflicting') if evidence['conflicts']
                      else 'available' if items else 'no_applicable_sources',
            'field_definitions': _definition_links(w, topic) if release_id is None else [],
            'retrieval': audit, 'scientific_authority': 'general_source_context'}
    if include_evidence:
        # Local frozen applicability only; never added to public retrieval queries.
        result['applicability_context'] = json.loads(json.dumps(context or {}))
        result['evidence_spans'] = list(spans.values())
        result['claim_reviews'] = list(reviews.values())
    return result


def answer_evidence(question):
    """Select complete, applicable explanations for this answer, without a rank cut.

    Retrieval has already checked authority and scope. This chooses its requested
    uses and removes duplicate exact claims; it does not grant any new authority.
    The stable ordering keeps an action from disappearing when retrieval order changes.
    """
    evidence = question.get('evidence') or {}
    needs = set(evidence.get('retrieval', {}).get('required_purposes') or PURPOSES)
    if question.get('steps') or question.get('action_reviews'):
        needs.add('action_or_reassessment')
    selected = {}
    for item in evidence.get('items', []):
        if (not item.get('statement') or not item.get('citations')
                or item.get('recommendation_allowed') is False):
            continue
        purposes = set(item.get('purposes', []))
        if purposes and not purposes & needs:
            continue
        selected[(item['claim_id'], item['version'])] = item
    order = {purpose: index for index, purpose in enumerate(PURPOSES)}
    return sorted(selected.values(), key=lambda item: (
        min((order[purpose] for purpose in item.get('purposes', []) if purpose in order), default=len(order)),
        item['claim_id'], item['version']))
