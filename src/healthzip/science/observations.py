"""Two explicit observation extensions; the original 77-metric registry is unchanged."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy

from healthzip.normalize import quantity_value

from .contracts import Window, result, select_as_of
from .state import stream_key

REGISTRY_VERSION = 'source-observations-1.5.0'
DEFINITIONS = {
    'OBS-VO2-REPORTED': {
        'metric_id': 'OBS-VO2-REPORTED', 'title': '来源报告的 VO₂max 记录', 'unit': 'mL/(kg·min)',
        'uncertainty': '来源报告值的测量方法和个人误差尚未核验；没有估计真实 VO₂max 或变化区间。',
        'forbidden_inferences': ['HealthKit 字段不能证明气体分析实测或准确生理真值。',
            '不混合来源、设备、协议或版本，不由相对值变化推断减重或训练的因果作用。'],
        'evidence_refs': [], 'canonical_type': 'vo2_max_ml_kg_min'},
    'OBS-CYCLE-RECORDS': {
        'metric_id': 'OBS-CYCLE-RECORDS', 'title': '已导入的月经类别记录', 'unit': 'source_records',
        'uncertainty': '这里只回顾已导入类别；记录数量不代表出血天数、月经周期数或生理状态。',
        'forbidden_inferences': ['缺少记录不等于没有月经，也不推断周期阶段、排卵、避孕或诊断。',
            '原始类别保持原值，不把未知类别或无出血记录改写为出血事实。',
            '不根据周期类别自动生成训练重量、恢复判断或训练处方。'],
        'evidence_refs': [], 'canonical_type': 'menstrual_flow'},
}


def definitions():
    return deepcopy(DEFINITIONS)


def evaluate(metric_id, records, *, cutoff_time, window_start, window_end, context=None):
    if metric_id not in DEFINITIONS:
        raise ValueError('unregistered_observation_id')
    context = dict(context or {})
    definition = DEFINITIONS[metric_id]
    window = Window(window_start, window_end, cutoff_time, context.get('timezone', 'UTC'))
    candidates = [r for r in records if r.get('canonical_type') == definition['canonical_type']]
    selected, excluded = select_as_of(candidates, window, retrospective=context.get('retrospective', False))
    streams, valid = defaultdict(list), []
    for row in selected:
        item = {'source_record_id': row['_source_id'], 'observed_at': row['_event_end'],
            'available_at': row.get('available_at') or row.get('ingested_at'),
            'original_start': row.get('event_start') or row.get('start_utc'),
            'original_end': row.get('event_end') or row.get('end_utc')}
        if metric_id == 'OBS-VO2-REPORTED':
            numeric = quantity_value(row)
            if numeric['value'] is None or numeric['value'] <= 0 or numeric['unit'] != definition['unit']:
                excluded.append({'id': row['_source_id'], 'reason': 'reported_vo2_value_or_unit_unusable'})
                continue
            item.update(value=numeric['value'], unit=numeric['unit'],
                numeric_provenance=numeric, value_identity='source_reported_method_unverified')
        else:
            category = row.get('category_value')
            if not isinstance(category, str) or not category.strip():
                excluded.append({'id': row['_source_id'], 'reason': 'recorded_category_missing'})
                continue
            item.update(recorded_category=category, category_interpretation='raw_source_category_not_inferred')
        streams[stream_key(row)].append(item)
        valid.append(row)
    value = {'streams': [{'source_name': key[0], 'device': key[1], 'protocol_id': key[2],
        'source_version': key[3], 'comparability': 'not_verified_by_source_grouping',
        'observations': items} for key, items in streams.items()]} if valid else None
    return result(metric_id, window, value, records=selected, valid_n=len(valid), total_n=len(selected),
        evidence_status='observed', data_status=('valid' if len(valid) == len(selected) else 'partial') if valid else 'insufficient',
        count_domain='imported_source_records',
        reasons=['source_records_only_not_physiological_truth'] + ([] if valid else ['no_usable_visible_source_records']),
        coverage=[{'kind': 'usable_visible_imported_records', 'numerator': len(valid), 'denominator': len(selected),
            'definition': 'Usable records among imported visible records in this endpoint window; expected sampling and physiological coverage are unknown.'}],
        algorithm_version=REGISTRY_VERSION, metric_registry=REGISTRY_VERSION, original_77_metric=False,
        exclusions=excluded)


def evaluate_all(records, **kwargs):
    return {mid: evaluate(mid, records, **kwargs) for mid in DEFINITIONS}
