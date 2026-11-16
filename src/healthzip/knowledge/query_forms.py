"""Explicit, versioned public query forms; never interpolate caller text or values."""
from __future__ import annotations

import json
from pathlib import Path

from .store import digest, dumps


def configuration():
    return json.loads((Path(__file__).parent / 'data/query_forms_v15.json').read_text())


def identity():
    return digest(dumps(configuration()).encode())


def select(metric_id, task_id, profiles, *, form=None):
    profile = profiles['profiles'][metric_id]
    if form is None:
        title = profiles['functions'][task_id]['title'] if task_id != 'explain_metric' else '指标解释'
        query = ' '.join([title, profile['query'], *profile.get('query_aliases', [])])
        metadata = {'form_id': 'legacy_combined', 'language': 'mixed', 'expression': 'combined',
                    'registry_version': None, 'registry_sha256': None}
    else:
        registry = configuration()
        if not isinstance(form, str) or form not in registry['forms']:
            raise ValueError('unknown_fixed_query_form')
        if metric_id not in registry['profiles'] or task_id not in registry['tasks']:
            raise ValueError('missing_fixed_query_form')
        query = registry['tasks'][task_id][form] + ' ' + registry['profiles'][metric_id][form]
        metadata = {'form_id': form, **registry['forms'][form],
                    'registry_version': registry['schema_version'], 'registry_sha256': identity()}
    metadata['input_sha256'] = digest(query.encode())
    return query, metadata
