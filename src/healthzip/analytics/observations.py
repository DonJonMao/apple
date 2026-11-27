"""Canonical observation adapters use the existing source revision ledger, never P1 cards."""
from healthzip.db.temporal_schema import current_source_rows, samples_as_of
from healthzip.science.contracts import canonical_hash
from healthzip.science.observations import REGISTRY_VERSION, definitions, evaluate_all


def for_repository(repo, *, cutoff_time, window_start, window_end, timezone_name='UTC', retrospective=False, source_filter=()):
    types = sorted(d['canonical_type'] for d in definitions().values())
    options = {'window_start': window_start, 'window_end': window_end, 'canonical_types': types}
    rows = (current_source_rows(repo, 'health_sample', **options) if retrospective else
            samples_as_of(repo, cutoff_time, 'health_sample', **options))
    records = []
    for original in rows:
        row = dict(original)
        row.update(record_kind='health_sample', raw_id=row['id'], id=f"health_sample:{row['id']}",
            event_start=row.get('start_utc'), event_end=row.get('end_utc'))
        row['source_name'] = row.get('source_name') or row.get('source_bundle_id') or row.get('source')
        if source_filter and row['source_name'] not in source_filter:
            continue
        records.append(row)
    metrics = evaluate_all(records, cutoff_time=cutoff_time, window_start=window_start, window_end=window_end,
        context={'timezone': timezone_name, 'retrospective': retrospective})
    return {'metrics': metrics, 'registry_version': REGISTRY_VERSION,
        'input_hash': canonical_hash({'records': records, 'cutoff_time': cutoff_time,
            'window_start': window_start, 'window_end': window_end, 'retrospective': retrospective}),
        'query_plan': {'table': 'health_sample', 'canonical_types': types, 'returned_records': len(records),
            'revision_policy': 'existing_latest_visible_revision_before_window_filter'}}
