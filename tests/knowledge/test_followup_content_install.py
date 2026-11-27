"""An added topic route must preserve the old claim and computed-context gates."""
import json

import pytest

from healthzip.knowledge import KnowledgeWorkbench, topics
from tests.integration.test_followup_report_evidence import claim
from tools import followup_knowledge_content_gaps as install


@pytest.fixture
def library(tmp_path):
    kb = KnowledgeWorkbench(tmp_path / 'synthetic-public-copy', environment_kind='synthetic_test')
    yield kb
    kb.close()


def existing_use(kb, monkeypatch, *, conditions=None):
    sid = claim(kb, 'synthetic-original-window-study', ['measurement', 'comparison'],
                bind=False, conditions=conditions)
    vid = sid.rsplit(':s', 1)[0]
    spec = {'id': 'synthetic-original-window-study', 'version': '1', 'reading': 'window',
            'spans': [0], 'need': 'hrv_missing_observation_unit'}
    monkeypatch.setattr(install, 'EXISTING_USES', [spec])
    monkeypatch.setattr(install, 'NEW_USES', [])
    monkeypatch.setattr(install, 'READINGS', {'window': {
        'source': spec['id'], 'version': vid, 'domain': 'wearable'}})
    monkeypatch.setattr(install, 'version', lambda reading: reading['version'])
    return spec


def test_existing_original_claim_and_review_remain_exact_and_rerun_is_idempotent(library, monkeypatch):
    spec = existing_use(library, monkeypatch)
    before = tuple(library.lib.theories.execute('SELECT * FROM source_claim WHERE claim_id=?', (spec['id'],)).fetchone())
    first = install.apply(library)
    second = install.apply(library)
    after = tuple(library.lib.theories.execute('SELECT * FROM source_claim WHERE claim_id=?', (spec['id'],)).fetchone())
    assert after == before and first == second
    assert first[0]['existing_claim_reused'] is True
    assert library.lib.theories.execute('SELECT count(*) FROM source_claim').fetchone()[0] == 1
    for topic in ['BODY-OBS-hrv_sdnn_ms', 'W2', 'W6']:
        answer = topics.question_sources(library, topic)
        assert [item['claim_id'] for item in answer['items']] == [spec['id']]
        assert answer['retrieval']['answer_status']['hrv_missing_observation_unit']['status'] == 'available'


def test_conditional_rir_claim_cannot_be_republished_without_computed_result(library, monkeypatch):
    existing_use(library, monkeypatch, conditions=[{
        'field': 'metric_evidence.direct_rir_only', 'op': 'eq', 'value': True,
        'origin': 'measurement_contract'}])
    before = library.lib.theories.execute('SELECT count(*) FROM knowledge_evidence_edge').fetchone()[0]
    with pytest.raises(ValueError, match='conditional_claim_requires_computed_context'):
        install.apply(library)
    assert library.lib.theories.execute('SELECT count(*) FROM knowledge_evidence_edge').fetchone()[0] == before


def test_preflight_rejects_changed_original_rights_before_adding_any_topic(library, monkeypatch):
    spec = existing_use(library, monkeypatch)
    with library.lib.sources:
        library.lib.sources.execute('UPDATE version SET rights_json=? WHERE source_id=?',
            (json.dumps({'license_id': 'restricted', 'index_allowed': False}), spec['id']))
    with pytest.raises(ValueError):
        install.apply(library)
    assert library.lib.theories.execute('SELECT count(*) FROM knowledge_evidence_edge').fetchone()[0] == 0
