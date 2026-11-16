"""Fixed form selection must preserve privacy and frozen query semantics."""
import json

import pytest
from test_v15_retrieval import CONTEXT, Embed, Rank, add, result

from healthzip.knowledge import domains, metric_retrieval, query_forms, vector_index
from healthzip.knowledge.model_services import QUERY_INSTRUCTION
from healthzip.knowledge.store import digest, dumps


def test_registry_is_complete_and_queries_are_separately_selected(kb):
    registry = query_forms.configuration()
    profiles = domains.configuration(include_observations=True)
    assert set(registry['profiles']) == set(profiles['profiles'])
    assert set(registry['tasks']) == {'explain_metric', *profiles['functions']}
    for mid in registry['profiles']:
        for task in ['explain_metric', *profiles['profiles'][mid]['analysis_functions']]:
            queries = [query_forms.select(mid, task, profiles, form=f)[0] for f in registry['forms']]
            assert len(set(queries)) == 3 and all(q.strip() for q in queries)
    query, audit = query_forms.select('STR-12', 'strength', profiles)
    assert query == ' '.join(['力量训练进阶', profiles['profiles']['STR-12']['query'],
                             *profiles['profiles']['STR-12']['query_aliases']])
    answer = kb.retrieve_for_metric('STR-12', 'strength', result(), CONTEXT, mode='lexical')
    assert answer['query_id'] == digest(dumps(['STR-12', 'strength', domains.profile_version('STR-12'), None]).encode())
    assert audit['input_sha256'] == digest(query.encode())


def test_model_queries_use_only_selected_form_and_never_private_context(kb):
    add(kb)
    embed, rank = Embed(), Rank()
    vector_index.build_vectors(kb, embed)
    embed.calls.clear()
    secret = 'PRIVATE-CONTEXT-query-form-98329'
    query_ids, hashes = set(), set()
    for form in query_forms.configuration()['forms']:
        answer = kb.retrieve_for_metric('STR-12', 'strength', result(),
            {**CONTEXT, 'notes': secret, 'health_values': [983.29387]}, services=(embed, rank), query_form=form)
        expected, meta = query_forms.select('STR-12', 'strength', domains.configuration(include_observations=True), form=form)
        assert embed.calls[-1]['input'] == [QUERY_INSTRUCTION + expected]
        assert json.loads(rank.calls[-1]['messages'][1]['content'])['task'] == expected
        assert answer['retrieval_audit']['query_form'] == meta
        query_ids.add(answer['query_id'])
        hashes.add(meta['input_sha256'])
    assert len(query_ids) == len(hashes) == 3
    assert secret not in json.dumps(embed.calls + rank.calls)
    assert '983.29387' not in json.dumps(embed.calls + rank.calls)
    with pytest.raises(ValueError, match='unknown_fixed_query_form'):
        kb.retrieve_for_metric('STR-12', 'strength', result(), CONTEXT, query_form=secret)
    # The shared product entry forwards an explicit form and retains the explanation contract.
    product = kb.explain_metric('STR-12', 'strength', result(), CONTEXT, query_form='en')
    assert product['evidence_context']['retrieval_audit']['query_form']['language'] == 'en'


def test_old_release_cannot_acquire_new_forms_and_new_release_pins_registry(kb, monkeypatch):
    add(kb)
    metric_retrieval.freeze_index(kb, 'new')
    row = kb.lib.sources.execute('SELECT manifest_json FROM index_release WHERE release_id=?', ('new',)).fetchone()
    manifest = json.loads(row[0])
    assert manifest.pop('query_forms_sha256') == query_forms.identity()
    serialized = dumps(manifest)
    # Simulate a pre-feature frozen manifest without mutating the current release.
    with kb.lib.sources:
        kb.lib.sources.execute('INSERT INTO index_release VALUES(?,?,?,?)', ('old', serialized, digest(serialized.encode()), '2026-11-17'))
    kb.retrieve_for_metric('STR-12', 'strength', result(), CONTEXT, 'old', mode='lexical')
    with pytest.raises(ValueError, match='frozen_release_does_not_pin_query_forms'):
        kb.retrieve_for_metric('STR-12', 'strength', result(), CONTEXT, 'old', mode='lexical', query_form='en')
    kb.retrieve_for_metric('STR-12', 'strength', result(), CONTEXT, 'new', mode='lexical', query_form='en')
    original = query_forms.configuration

    def changed():
        value = original()
        value['profiles']['STR-12']['en'] += ' changed'
        return value

    monkeypatch.setattr(query_forms, 'configuration', changed)
    with pytest.raises(ValueError, match='frozen_query_forms_configuration_changed'):
        kb.retrieve_for_metric('STR-12', 'strength', result(), CONTEXT, 'new', mode='lexical')
    # The historical manifest still resolves the unchanged legacy combined query.
    kb.retrieve_for_metric('STR-12', 'strength', result(), CONTEXT, 'old', mode='lexical')
