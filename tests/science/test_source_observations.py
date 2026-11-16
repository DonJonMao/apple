"""Source observations obey the existing contract without inventing physiological states."""
import json
from pathlib import Path

import jsonschema
import pytest

from healthzip.ai.client import build_evidence_payload
from healthzip.science import definitions as original_definitions
from healthzip.science.observations import definitions, evaluate, evaluate_all

BOUNDS = {'cutoff_time': '2026-11-17T00:00:00+00:00', 'window_start': '2026-11-01T00:00:00+00:00',
    'window_end': '2026-11-17T00:00:00+00:00'}


def vo2(identity='observed', **overrides):
    return {'id': identity, 'canonical_type': 'vo2_max_ml_kg_min', 'source_name': 'Synthetic public fixture',
        'device': 'synthetic-device', 'source_version': '1', 'event_start': '2026-11-10T07:00:00+00:00',
        'event_end': '2026-11-10T08:00:00+00:00', 'available_at': '2026-11-10T09:00:00+00:00',
        'raw_value': '43.1256789', 'raw_unit': 'mL/kg/min', 'normalized_value': 999, 'normalized_unit': 'wrong',
        'notes': 'PRIVATE NOTE 193847', **overrides}


def flow(identity='flow', **overrides):
    return {**vo2(identity), 'canonical_type': 'menstrual_flow',
        'category_value': 'HKCategoryValueMenstrualFlowNone', **overrides}


def test_extensions_are_separate_from_77_and_empty_records_do_not_become_zero():
    assert len(original_definitions()) == 77
    assert not set(definitions()) & set(original_definitions())
    assert len(original_definitions(include_observations=True)) == 79
    schema = json.loads(Path('specs/v1.3/Codex_Execution_Pack_v1.3/metric_result.schema.json').read_text())
    for metric in evaluate_all([], **BOUNDS).values():
        jsonschema.validate(metric, schema)
        assert metric['value'] is None and metric['data_status'] == 'insufficient'
        assert metric['evidence_status'] == 'observed' and metric['original_77_metric'] is False
        assert metric['valid_n'] == metric['total_n'] == 0
        assert metric['calibration_artifact_id'] is None


def test_reported_vo2_keeps_raw_numeric_provenance_and_separates_device_and_version():
    records = [vo2(), vo2('other-device', device='device-b'), vo2('other-version', source_version='2')]
    metric = evaluate('OBS-VO2-REPORTED', records, **BOUNDS)
    assert len(metric['value']['streams']) == 3 and metric['valid_n'] == 3
    item = metric['value']['streams'][0]['observations'][0]
    assert item['value'] == 43.1256789 and item['unit'] == 'mL/(kg·min)'
    assert item['numeric_provenance']['raw_value'] == '43.1256789'
    assert item['numeric_provenance']['reprocessed_from_raw'] is True
    assert item['value_identity'] == 'source_reported_method_unverified'
    assert metric['uncertainty']['kind'] == 'not_estimated'
    assert 'slope' not in json.dumps(metric)
    assert records[0]['normalized_value'] == 999  # Original source rows were not changed.


@pytest.mark.parametrize('changes', [{'raw_value': '-1'}, {'raw_value': 'nan'}, {'raw_unit': 'unknown'},
    {'raw_value': None, 'unit_status': 'unit_unverified', 'normalized_unit': 'mL/(kg·min)', 'normalized_value': 40}])
def test_unusable_values_do_not_become_physiological_observations(changes):
    metric = evaluate('OBS-VO2-REPORTED', [vo2(**changes)], **BOUNDS)
    assert metric['value'] is None and metric['valid_n'] == 0 and metric['total_n'] == 1
    assert metric['exclusions'][0]['reason'] == 'reported_vo2_value_or_unit_unusable'


def test_revisions_availability_and_half_open_window_do_not_resurrect_previous_values():
    old = vo2('old', source_record_id='stable')
    changed = vo2('changed', source_record_id='stable', available_at='2026-11-16T12:00:00+00:00',
        event_end='2026-11-18T00:00:00+00:00')
    after_window = vo2('boundary', event_end=BOUNDS['window_end'])
    unavailable = vo2('late', available_at='2026-11-18T00:00:00+00:00')
    metric = evaluate('OBS-VO2-REPORTED', [old, changed, after_window, unavailable], **BOUNDS)
    assert metric['value'] is None
    assert {e['reason'] for e in metric['exclusions']} >= {
        'superseded_as_of', 'event_after_cutoff', 'available_after_cutoff', 'outside_window'}
    # A revision not yet visible must not replace the earlier observed record.
    changed['available_at'] = '2026-11-18T12:00:00+00:00'
    metric = evaluate('OBS-VO2-REPORTED', [old, changed], **BOUNDS)
    assert metric['source_record_ids'] == ['old']


def test_cycle_preserves_none_unknown_and_repeated_categories_without_counting_cycles_or_days():
    metric = evaluate('OBS-CYCLE-RECORDS', [flow(), flow('unknown', category_value='Unknown source enum'),
        flow('same-date', category_value='HKCategoryValueMenstrualFlowNone')], **BOUNDS)
    items = metric['value']['streams'][0]['observations']
    assert metric['valid_n'] == 3 and len(items) == 3
    assert [x['recorded_category'] for x in items] == ['HKCategoryValueMenstrualFlowNone',
        'Unknown source enum', 'HKCategoryValueMenstrualFlowNone']
    assert all(x['category_interpretation'] == 'raw_source_category_not_inferred' for x in items)
    assert set(metric['value']) == {'streams'}
    assert not any(key in metric['value'] for key in ['phase', 'ovulation', 'bleeding_days', 'cycle_count'])
    empty = evaluate('OBS-CYCLE-RECORDS', [flow(category_value=None)], **BOUNDS)
    assert empty['value'] is None and empty['total_n'] == 1


def test_unknown_visibility_requires_retrospective_label_and_network_projection_keeps_details_local():
    record = vo2(available_at=None)
    assert evaluate('OBS-VO2-REPORTED', [record], **BOUNDS)['value'] is None
    metric = evaluate('OBS-VO2-REPORTED', [record], context={'retrospective': True}, **BOUNDS)
    assert 'retrospective_snapshot_not_prospective' in metric['reason_codes']
    cycle = evaluate('OBS-CYCLE-RECORDS', [flow()], **BOUNDS)
    payload = build_evidence_payload({'metrics': [metric, cycle]})
    sent = json.dumps(payload)
    assert '43.1256789' not in sent and '193847' not in sent and 'synthetic-device' not in sent
    assert 'HKCategoryValueMenstrualFlowNone' not in sent and 'OBS-CYCLE-RECORDS' not in sent
    assert payload['evidence'][0]['id'] == 'OBS-VO2-REPORTED'
